"""
calibration.py — Calibration System for the High-Fidelity Digital Twin

Loads, validates, saves, and manages calibration profiles that tune
the twin's parameters to match real-world machine behavior.

Calibration profile schema:
{
  "name":        str,
  "description": str,
  "parameters": {
    "motor": {
      "startup_delay_ms": int,
      "stop_delay_ms":    int
    },
    "shuttle": {
      "speed_units_per_sec": float,
      "cycle_length":        float
    },
    "sensor": {
      "threshold":    float,
      "window":       float,
      "delay_ms":     int,
      "miss_every_n": int
    }
  }
}

STRICT RULES:
  - No randomness.
  - Calibration does NOT modify core simulation logic.
  - All profiles are JSON-serialisable and deterministic.
"""

import json
import os


# ---------------------------------------------------------------------------
# Default profile — matches the twin's constructor defaults
# ---------------------------------------------------------------------------

DEFAULT_PROFILE = {
    "name":        "default",
    "description": "Default parameters matching twin constructor defaults",
    "parameters": {
        "motor": {
            "startup_delay_ms": 300,
            "stop_delay_ms":    200
        },
        "shuttle": {
            "speed_units_per_sec": 100.0,
            "cycle_length":        360.0
        },
        "sensor": {
            "threshold":    180.0,
            "window":       20.0,
            "delay_ms":     0,
            "miss_every_n": 0
        }
    }
}

# Required keys for validation
_REQUIRED_STRUCTURE = {
    "motor":   {"startup_delay_ms", "stop_delay_ms"},
    "shuttle": {"speed_units_per_sec", "cycle_length"},
    "sensor":  {"threshold", "window", "delay_ms", "miss_every_n"}
}


def validate_profile(profile):
    """
    Validate a calibration profile dict.

    Returns:
        {"valid": bool, "errors": [str, ...]}
    """
    errors = []

    if "name" not in profile:
        errors.append("missing 'name'")
    if "parameters" not in profile:
        errors.append("missing 'parameters'")
        return {"valid": False, "errors": errors}

    params = profile["parameters"]
    for section, keys in _REQUIRED_STRUCTURE.items():
        if section not in params:
            errors.append(f"missing parameters.{section}")
            continue
        for key in keys:
            if key not in params[section]:
                errors.append(f"missing parameters.{section}.{key}")

    # Type checks
    try:
        m = params.get("motor", {})
        assert isinstance(m.get("startup_delay_ms"), int)
        assert isinstance(m.get("stop_delay_ms"), int)
        s = params.get("shuttle", {})
        assert isinstance(s.get("speed_units_per_sec"), (int, float))
        assert isinstance(s.get("cycle_length"), (int, float))
        sen = params.get("sensor", {})
        assert isinstance(sen.get("threshold"), (int, float))
        assert isinstance(sen.get("window"), (int, float))
        assert isinstance(sen.get("delay_ms"), int)
        assert isinstance(sen.get("miss_every_n"), int)
    except (AssertionError, TypeError):
        errors.append("one or more parameter values have wrong type")

    return {"valid": len(errors) == 0, "errors": errors}


def load_profile(filepath):
    """
    Load a calibration profile from a JSON file.

    Args:
        filepath : str — path to .json profile file

    Returns:
        dict — calibration profile

    Raises:
        FileNotFoundError, ValueError (invalid profile)
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Profile not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        profile = json.load(f)

    result = validate_profile(profile)
    if not result["valid"]:
        raise ValueError(f"Invalid profile: {result['errors']}")

    return profile


def save_profile(profile, filepath):
    """
    Save a calibration profile to a JSON file.

    Args:
        profile  : dict — calibration profile
        filepath : str  — output path
    """
    result = validate_profile(profile)
    if not result["valid"]:
        raise ValueError(f"Cannot save invalid profile: {result['errors']}")

    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath)
                else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)


def get_param(profile, section, key):
    """Convenience accessor: profile['parameters'][section][key]."""
    return profile["parameters"][section][key]


def build_twin_from_profile(profile, step_ms=100):
    """
    Instantiate all twin components from a calibration profile.

    Args:
        profile : dict — calibration profile
        step_ms : int  — simulation tick size (for sensor buffer sizing)

    Returns:
        dict with keys: "motor", "shuttle", "sensor"
    """
    from loom_twin import (MotorStateMachine, CyclicShuttleModel,
                           DelayedSensor)

    m   = profile["parameters"]["motor"]
    s   = profile["parameters"]["shuttle"]
    sen = profile["parameters"]["sensor"]

    motor   = MotorStateMachine(
        startup_delay_ms=m["startup_delay_ms"],
        stop_delay_ms=m["stop_delay_ms"]
    )
    shuttle = CyclicShuttleModel(
        speed_units_per_sec=s["speed_units_per_sec"],
        cycle_length=s["cycle_length"]
    )
    sensor  = DelayedSensor(
        threshold=sen["threshold"],
        window=sen["window"],
        delay_ms=sen["delay_ms"],
        step_ms=step_ms,
        miss_every_n=sen["miss_every_n"]
    )

    return {"motor": motor, "shuttle": shuttle, "sensor": sensor}


# ---------------------------------------------------------------------------
# STEP 2: Measurement Functions
# ---------------------------------------------------------------------------

def measure_twin(profile, step_ms=100, max_time_ms=20000):
    """
    Run a simulation with the given profile and measure key behaviors.

    Measurements:
      - motor_start_delay_ms  : time from command ON to RUNNING state
      - motor_stop_delay_ms   : time from command OFF to STOPPED state
      - cycle_time_ms         : time for one full shuttle cycle (ms)
      - sensor_trigger_time_ms: time from motor RUNNING to first sensor activation
      - sensor_active_duration_ms: how long sensor stays active per trigger

    Args:
        profile     : dict — calibration profile
        step_ms     : int  — tick size in ms
        max_time_ms : int  — simulation time limit

    Returns:
        dict of measurements (None if not observed within max_time_ms)
    """
    from loom_twin import MotorState

    twin = build_twin_from_profile(profile, step_ms)
    motor   = twin["motor"]
    shuttle = twin["shuttle"]
    sensor  = twin["sensor"]

    motor.command(True)

    # Tracking variables
    motor_start_delay_ms      = None
    motor_stop_delay_ms       = None
    cycle_time_ms             = None
    sensor_trigger_time_ms    = None
    sensor_active_duration_ms = None

    command_on_time   = 0       # t=0 we issue command ON
    running_start_t   = None    # when motor entered RUNNING
    first_cycle_start = None    # time of first wrap (cycle start)
    sensor_on_time    = None    # when sensor first went active
    running_reached   = False
    stop_issued       = False
    stop_issued_time  = None
    prev_sensor       = False
    prev_cycles       = 0

    for t in range(0, max_time_ms + step_ms, step_ms):
        # Issue stop command after 2 full cycles to measure stop delay
        # Command issued BEFORE update so STOPPING starts this tick
        if (shuttle.cycles_completed >= 2 and not stop_issued
                and motor_stop_delay_ms is None):
            motor.command(False)
            stop_issued      = True
            stop_issued_time = t

        state = motor.update(t)
        pos   = shuttle.update(t, motor.is_running)
        sen   = sensor.update(pos)

        # Motor start delay: command ON → RUNNING
        if not running_reached and state == MotorState.RUNNING:
            motor_start_delay_ms = t - command_on_time
            running_start_t      = t
            running_reached      = True

        # Cycle time: time between consecutive cycle completions
        if shuttle.cycles_completed > prev_cycles:
            if first_cycle_start is None:
                first_cycle_start = t
            elif cycle_time_ms is None:
                cycle_time_ms = t - first_cycle_start
                first_cycle_start = t
            prev_cycles = shuttle.cycles_completed

        # Sensor trigger time: RUNNING → first sensor activation
        if running_reached and sensor_trigger_time_ms is None:
            if sen and not prev_sensor:
                sensor_trigger_time_ms = t - running_start_t

        # Sensor active duration: how long sensor stays ON
        if sen and not prev_sensor:
            sensor_on_time = t
        if not sen and prev_sensor and sensor_on_time is not None:
            if sensor_active_duration_ms is None:
                sensor_active_duration_ms = t - sensor_on_time

        prev_sensor = sen

        # Motor stop delay: command OFF → STOPPED
        if stop_issued and state == MotorState.STOPPED and motor_stop_delay_ms is None:
            motor_stop_delay_ms = t - stop_issued_time

        # Stop once all measurements collected
        if all(v is not None for v in [
            motor_start_delay_ms, motor_stop_delay_ms,
            cycle_time_ms, sensor_trigger_time_ms,
            sensor_active_duration_ms
        ]):
            break

    return {
        "motor_start_delay_ms":      motor_start_delay_ms,
        "motor_stop_delay_ms":       motor_stop_delay_ms,
        "cycle_time_ms":             cycle_time_ms,
        "sensor_trigger_time_ms":    sensor_trigger_time_ms,
        "sensor_active_duration_ms": sensor_active_duration_ms
    }


def print_measurements(measurements, profile_name=""):
    """Print measurements in a readable format."""
    label = f" ({profile_name})" if profile_name else ""
    print(f"  Measurements{label}:")
    for key, val in measurements.items():
        unit = "ms"
        display = f"{val}{unit}" if val is not None else "not observed"
        print(f"    {key:<30} : {display}")


# ---------------------------------------------------------------------------
# STEP 3: Error Calculation
# ---------------------------------------------------------------------------

def calculate_errors(measured, expected):
    """
    Compare measured values against expected (real-world) values.

    For each key present in both dicts, computes:
      - absolute_error : |measured - expected|
      - relative_error : |measured - expected| / expected  (as %)
      - within_tolerance: bool (True if abs_error <= tolerance)

    Args:
        measured : dict — output of measure_twin()
        expected : dict — target values from real-world observations
                   e.g. {"motor_start_delay_ms": 280, "cycle_time_ms": 3500}

    Returns:
        dict keyed by measurement name:
        {
          "<key>": {
            "measured":          float | None,
            "expected":          float,
            "absolute_error":    float | None,
            "relative_error_pct": float | None,
          }
        }
    """
    errors = {}

    for key, exp_val in expected.items():
        meas_val = measured.get(key)

        if meas_val is None or exp_val is None:
            errors[key] = {
                "measured":           meas_val,
                "expected":           exp_val,
                "absolute_error":     None,
                "relative_error_pct": None,
            }
            continue

        abs_err = abs(meas_val - exp_val)
        rel_err = round(abs_err / exp_val * 100, 2) if exp_val != 0 else None

        errors[key] = {
            "measured":           meas_val,
            "expected":           exp_val,
            "absolute_error":     abs_err,
            "relative_error_pct": rel_err,
        }

    return errors


def total_error_score(errors):
    """
    Compute a single scalar error score from an error dict.

    Score = mean of all relative_error_pct values (ignoring None).
    Lower is better. Returns None if no valid errors.
    """
    values = [
        e["relative_error_pct"]
        for e in errors.values()
        if e["relative_error_pct"] is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def print_errors(errors, title="Error Report"):
    """Print error comparison in a readable table."""
    print(f"  {title}:")
    print(f"  {'Parameter':<30}  {'Expected':>10}  {'Measured':>10}  "
          f"{'AbsErr':>8}  {'RelErr%':>8}")
    print("  " + "-" * 72)
    for key, e in errors.items():
        exp  = f"{e['expected']}"  if e['expected']  is not None else "N/A"
        meas = f"{e['measured']}"  if e['measured']  is not None else "N/A"
        aerr = f"{e['absolute_error']}" if e['absolute_error'] is not None else "N/A"
        rerr = f"{e['relative_error_pct']}%" if e['relative_error_pct'] is not None else "N/A"
        print(f"  {key:<30}  {exp:>10}  {meas:>10}  {aerr:>8}  {rerr:>8}")
    score = total_error_score(errors)
    print(f"  {'':30}  {'':>10}  {'':>10}  {'':>8}  {'Score':>8}")
    print(f"  {'Mean relative error':30}  {'':>10}  {'':>10}  {'':>8}  "
          f"{f'{score}%' if score is not None else 'N/A':>8}")


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 9 - Step 3: Error Calculation")
    print("=" * 60)

    # Simulated "real-world" observations — slightly different from defaults
    # (as if the real machine runs a bit faster and has a shorter startup)
    REAL_WORLD = {
        "motor_start_delay_ms":      280,   # real: 280ms, sim: 300ms
        "motor_stop_delay_ms":       190,   # real: 190ms, sim: 200ms
        "cycle_time_ms":             3500,  # real: 3500ms, sim: 3600ms
        "sensor_trigger_time_ms":    1650,  # real: 1650ms, sim: 1700ms
        "sensor_active_duration_ms": 195,   # real: 195ms,  sim: 200ms
    }

    # -------------------------------------------------------
    # Test 1: default profile vs real world
    # -------------------------------------------------------
    print("\nTest 1 — Default profile vs real-world observations:")
    measured1 = measure_twin(DEFAULT_PROFILE, step_ms=100)
    print_measurements(measured1, "default")

    errors1 = calculate_errors(measured1, REAL_WORLD)
    print()
    print_errors(errors1, "Default vs Real-World")
    score1 = total_error_score(errors1)
    print(f"\n  Total error score: {score1}%")

    # -------------------------------------------------------
    # Test 2: perfect match (measured == expected)
    # -------------------------------------------------------
    print("\nTest 2 — Perfect match (measured == expected):")
    perfect_measured = dict(REAL_WORLD)
    errors_perfect = calculate_errors(perfect_measured, REAL_WORLD)
    print_errors(errors_perfect, "Perfect Match")
    score_perfect = total_error_score(errors_perfect)
    print(f"\n  Total error score: {score_perfect}%")

    # -------------------------------------------------------
    # Test 3: large mismatch
    # -------------------------------------------------------
    print("\nTest 3 — Large mismatch (fast profile vs real-world):")
    fast_profile = {
        "name": "fast", "description": "Fast",
        "parameters": {
            "motor":   {"startup_delay_ms": 150, "stop_delay_ms": 100},
            "shuttle": {"speed_units_per_sec": 200.0, "cycle_length": 360.0},
            "sensor":  {"threshold": 180.0, "window": 20.0,
                        "delay_ms": 0, "miss_every_n": 0}
        }
    }
    measured3 = measure_twin(fast_profile, step_ms=100)
    errors3 = calculate_errors(measured3, REAL_WORLD)
    print_errors(errors3, "Fast Profile vs Real-World")
    score3 = total_error_score(errors3)
    print(f"\n  Total error score: {score3}%")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Perfect match → all errors = 0
    for key, e in errors_perfect.items():
        assert e["absolute_error"] == 0,    f"perfect: {key} abs_error must be 0"
        assert e["relative_error_pct"] == 0.0
    assert score_perfect == 0.0
    print("  PASS — perfect match: all errors = 0, score = 0.0%")

    # Default vs real: errors are small but non-zero
    assert errors1["motor_start_delay_ms"]["absolute_error"] == 20
    assert errors1["cycle_time_ms"]["absolute_error"] == 100
    assert score1 > 0.0
    print(f"  PASS — default vs real: motor_start abs_err=20ms, "
          f"cycle abs_err=100ms, score={score1}%")

    # Fast profile has larger errors than default
    assert score3 > score1, \
        f"fast profile must have larger error than default: {score3} vs {score1}"
    print(f"  PASS — fast profile error ({score3}%) > default error ({score1}%)")

    # All error entries have required keys
    for key, e in errors1.items():
        for field in ("measured", "expected", "absolute_error",
                      "relative_error_pct"):
            assert field in e, f"missing field {field} in {key}"
    print("  PASS — all error entries have required fields")
