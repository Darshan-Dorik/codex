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


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 9 - Step 2: Measurement Functions")
    print("=" * 60)

    # --- Test 1: measure default profile ---
    print("\nTest 1 — Measure default profile:")
    m1 = measure_twin(DEFAULT_PROFILE, step_ms=100)
    print_measurements(m1, "default")

    # --- Test 2: measure fast profile (different speed) ---
    print("\nTest 2 — Measure fast profile (speed=200, startup=150ms):")
    fast_profile = {
        "name": "fast",
        "description": "Fast loom",
        "parameters": {
            "motor":   {"startup_delay_ms": 150, "stop_delay_ms": 100},
            "shuttle": {"speed_units_per_sec": 200.0, "cycle_length": 360.0},
            "sensor":  {"threshold": 180.0, "window": 20.0,
                        "delay_ms": 0, "miss_every_n": 0}
        }
    }
    m2 = measure_twin(fast_profile, step_ms=100)
    print_measurements(m2, "fast")

    # --- Test 3: measure with sensor delay ---
    print("\nTest 3 — Measure with 200ms sensor delay:")
    delayed_profile = {
        "name": "delayed_sensor",
        "description": "Sensor with 200ms delay",
        "parameters": {
            "motor":   {"startup_delay_ms": 300, "stop_delay_ms": 200},
            "shuttle": {"speed_units_per_sec": 100.0, "cycle_length": 360.0},
            "sensor":  {"threshold": 180.0, "window": 20.0,
                        "delay_ms": 200, "miss_every_n": 0}
        }
    }
    m3 = measure_twin(delayed_profile, step_ms=100)
    print_measurements(m3, "delayed_sensor")

    # --- Assertions ---
    print("\n--- Assertions ---")

    # Default profile: motor start = 300ms, stop = 200ms
    assert m1["motor_start_delay_ms"] == 300, \
        f"expected 300ms start delay, got {m1['motor_start_delay_ms']}"
    assert m1["motor_stop_delay_ms"]  == 200, \
        f"expected 200ms stop delay, got {m1['motor_stop_delay_ms']}"
    print(f"  PASS — default: start={m1['motor_start_delay_ms']}ms "
          f"stop={m1['motor_stop_delay_ms']}ms")

    # Default: cycle_time = cycle_length / speed = 360/100 = 3600ms
    assert m1["cycle_time_ms"] == 3600, \
        f"expected 3600ms cycle, got {m1['cycle_time_ms']}"
    print(f"  PASS — default: cycle_time={m1['cycle_time_ms']}ms")

    # Fast profile: start delay rounds up to next tick (150ms → 200ms at 100ms steps)
    # cycle=360/200=1800ms
    assert m2["motor_start_delay_ms"] == 200, \
        f"expected 200ms (150ms rounds up to 100ms tick), got {m2['motor_start_delay_ms']}"
    assert m2["cycle_time_ms"] == 1800, \
        f"expected 1800ms cycle, got {m2['cycle_time_ms']}"
    print(f"  PASS — fast: start={m2['motor_start_delay_ms']}ms "
          f"(150ms delay, 100ms ticks) cycle={m2['cycle_time_ms']}ms")

    # Delayed sensor: trigger time should be > default trigger time
    assert m3["sensor_trigger_time_ms"] > m1["sensor_trigger_time_ms"], \
        "delayed sensor must trigger later than no-delay sensor"
    print(f"  PASS — delayed sensor triggers later: "
          f"{m3['sensor_trigger_time_ms']}ms vs {m1['sensor_trigger_time_ms']}ms")

    # All measurements must be non-None
    for key, val in m1.items():
        assert val is not None, f"default: {key} must be measured"
    print("  PASS — all measurements observed for default profile")
