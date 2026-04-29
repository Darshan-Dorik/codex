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


# ---------------------------------------------------------------------------
# STEP 4: Calibration Report
# ---------------------------------------------------------------------------

def build_calibration_report(profile, measured, expected):
    """
    Build a structured calibration report dict.

    Schema:
    {
      "profile_name": str,
      "score":        float,   # mean relative error %
      "parameters": [
        {
          "parameter":  str,
          "expected":   float,
          "simulated":  float,
          "error":      float,   # absolute error
          "error_pct":  float    # relative error %
        }
      ]
    }

    Args:
        profile  : dict — calibration profile
        measured : dict — output of measure_twin()
        expected : dict — real-world target values

    Returns:
        dict — calibration report
    """
    errors = calculate_errors(measured, expected)
    score  = total_error_score(errors)

    parameters = []
    for key, e in errors.items():
        parameters.append({
            "parameter": key,
            "expected":  e["expected"],
            "simulated": e["measured"],
            "error":     e["absolute_error"],
            "error_pct": e["relative_error_pct"]
        })

    return {
        "profile_name": profile.get("name", "unknown"),
        "score":        score,
        "parameters":   parameters
    }


def print_calibration_report(report):
    """Print a calibration report in a clean structured format."""
    print("=" * 60)
    print(f"  CALIBRATION REPORT — {report['profile_name']}")
    print("=" * 60)
    print(f"  Overall score: {report['score']}%  "
          f"({'GOOD' if report['score'] is not None and report['score'] < 5 else 'NEEDS TUNING'})")
    print()
    print(f"  {'Parameter':<30}  {'Expected':>10}  {'Simulated':>10}  "
          f"{'Error':>8}  {'Error%':>8}")
    print("  " + "-" * 72)
    for p in report["parameters"]:
        exp  = f"{p['expected']}"  if p['expected']  is not None else "N/A"
        sim  = f"{p['simulated']}" if p['simulated'] is not None else "N/A"
        err  = f"{p['error']}"     if p['error']     is not None else "N/A"
        errp = f"{p['error_pct']}%" if p['error_pct'] is not None else "N/A"
        print(f"  {p['parameter']:<30}  {exp:>10}  {sim:>10}  "
              f"{err:>8}  {errp:>8}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# STEP 5: Iterative Calibration Loop
# ---------------------------------------------------------------------------

import copy


def _apply_adjustment(profile, param_key, delta):
    """
    Return a new profile with one parameter adjusted by delta.

    Mapping from measurement key → profile parameter path:
      motor_start_delay_ms      → motor.startup_delay_ms   (int, step=10)
      motor_stop_delay_ms       → motor.stop_delay_ms      (int, step=10)
      cycle_time_ms             → shuttle.speed_units_per_sec (derived)
      sensor_trigger_time_ms    → sensor.threshold         (float, step=5)
      sensor_active_duration_ms → sensor.window            (float, step=5)
    """
    p = copy.deepcopy(profile)
    params = p["parameters"]

    if param_key == "motor_start_delay_ms":
        params["motor"]["startup_delay_ms"] = max(
            0, params["motor"]["startup_delay_ms"] + int(delta))

    elif param_key == "motor_stop_delay_ms":
        params["motor"]["stop_delay_ms"] = max(
            0, params["motor"]["stop_delay_ms"] + int(delta))

    elif param_key == "cycle_time_ms":
        # cycle_time = cycle_length / speed  →  speed = cycle_length / cycle_time
        # Adjust speed so simulated cycle_time moves toward expected
        # delta here is the error in ms: positive means sim is too slow
        cycle_len = params["shuttle"]["cycle_length"]
        current_speed = params["shuttle"]["speed_units_per_sec"]
        # New target cycle time = current_cycle_time - delta
        current_cycle_ms = cycle_len / current_speed * 1000
        new_cycle_ms = max(100, current_cycle_ms - delta)
        params["shuttle"]["speed_units_per_sec"] = round(
            cycle_len / (new_cycle_ms / 1000), 4)

    elif param_key == "sensor_trigger_time_ms":
        # Sensor fires when position = threshold
        # position = speed * time  →  threshold = speed * trigger_time_s
        # Adjust threshold proportionally
        params["sensor"]["threshold"] = max(
            0.0, params["sensor"]["threshold"] + delta)

    elif param_key == "sensor_active_duration_ms":
        # active_duration = window / speed
        # Adjust window proportionally
        params["sensor"]["window"] = max(
            1.0, params["sensor"]["window"] + delta)

    return p


def calibrate(profile, expected, step_ms=100, max_iterations=20,
              tolerance_pct=1.0, verbose=True):
    """
    Iteratively adjust profile parameters to minimise error score.

    Algorithm: coordinate descent — for each parameter, try a small
    adjustment in both directions; keep the one that reduces total error.

    Args:
        profile        : dict  — starting calibration profile
        expected       : dict  — real-world target measurements
        step_ms        : int   — simulation tick size
        max_iterations : int   — max calibration iterations
        tolerance_pct  : float — stop when score <= this value
        verbose        : bool  — print progress

    Returns:
        {
          "profile":    dict,   # best calibrated profile
          "history":    [...],  # score per iteration
          "iterations": int,
          "converged":  bool
        }
    """
    current_profile = copy.deepcopy(profile)
    history = []

    # Step sizes for each parameter (in measurement units)
    step_sizes = {
        "motor_start_delay_ms":      50,
        "motor_stop_delay_ms":       50,
        "cycle_time_ms":             100,
        "sensor_trigger_time_ms":    5.0,
        "sensor_active_duration_ms": 5.0,
    }

    # Initial score
    measured = measure_twin(current_profile, step_ms)
    score    = total_error_score(calculate_errors(measured, expected))
    history.append(round(score, 4))

    if verbose:
        print(f"  Iteration  0: score={score:.2f}%")

    for iteration in range(1, max_iterations + 1):
        improved = False

        for param_key in step_sizes:
            if param_key not in expected:
                continue

            step = step_sizes[param_key]
            best_profile = current_profile
            best_score   = score

            for direction in (+1, -1):
                delta = direction * step
                candidate = _apply_adjustment(current_profile, param_key, delta)
                m = measure_twin(candidate, step_ms)
                s = total_error_score(calculate_errors(m, expected))
                if s is not None and s < best_score:
                    best_score   = s
                    best_profile = candidate

            if best_score < score:
                current_profile = best_profile
                score           = best_score
                improved        = True

        history.append(round(score, 4))

        if verbose:
            print(f"  Iteration {iteration:>2}: score={score:.2f}%"
                  f"{'  ← improved' if improved else ''}")

        if score <= tolerance_pct:
            if verbose:
                print(f"  Converged at iteration {iteration} "
                      f"(score={score:.2f}% ≤ {tolerance_pct}%)")
            return {
                "profile":    current_profile,
                "history":    history,
                "iterations": iteration,
                "converged":  True
            }

        if not improved:
            if verbose:
                print(f"  No improvement at iteration {iteration} — stopping")
            break

    return {
        "profile":    current_profile,
        "history":    history,
        "iterations": len(history) - 1,
        "converged":  score <= tolerance_pct
    }


# ---------------------------------------------------------------------------
# STEP 6: Calibration Profiles
# ---------------------------------------------------------------------------

class ProfileRegistry:
    """
    Manages a collection of named calibration profiles.

    Supports:
      - Registering profiles by name
      - Switching the active profile
      - Listing all profiles
      - Comparing profiles by error score
    """

    def __init__(self):
        self._profiles = {}
        self._active   = None

    def register(self, profile):
        """Add or replace a profile by its name."""
        name = profile.get("name")
        if not name:
            raise ValueError("Profile must have a 'name' field")
        result = validate_profile(profile)
        if not result["valid"]:
            raise ValueError(f"Invalid profile: {result['errors']}")
        self._profiles[name] = copy.deepcopy(profile)

    def activate(self, name):
        """Set the active profile by name."""
        if name not in self._profiles:
            raise KeyError(f"Profile '{name}' not registered")
        self._active = name

    def get_active(self):
        """Return the currently active profile."""
        if self._active is None:
            raise RuntimeError("No active profile set")
        return self._profiles[self._active]

    def get(self, name):
        """Return a profile by name."""
        if name not in self._profiles:
            raise KeyError(f"Profile '{name}' not found")
        return self._profiles[name]

    def list_names(self):
        """Return list of all registered profile names."""
        return list(self._profiles.keys())

    def compare(self, expected, step_ms=100):
        """
        Measure and score all registered profiles against expected values.

        Returns:
            list of {"name": str, "score": float} sorted by score (best first)
        """
        results = []
        for name, profile in self._profiles.items():
            measured = measure_twin(profile, step_ms)
            score    = total_error_score(calculate_errors(measured, expected))
            results.append({"name": name, "score": score})
        return sorted(results, key=lambda r: (r["score"] is None, r["score"]))

    def save_all(self, directory="outputs/profiles"):
        """Save all registered profiles to individual JSON files."""
        os.makedirs(directory, exist_ok=True)
        for name, profile in self._profiles.items():
            path = os.path.join(directory, f"{name}.json")
            save_profile(profile, path)
        return directory

    def load_directory(self, directory):
        """Load all .json files from a directory as profiles."""
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"Directory not found: {directory}")
        loaded = []
        for fname in sorted(os.listdir(directory)):
            if fname.endswith(".json"):
                path = os.path.join(directory, fname)
                try:
                    profile = load_profile(path)
                    self.register(profile)
                    loaded.append(profile["name"])
                except (ValueError, KeyError):
                    pass   # skip invalid files
        return loaded


# ---------------------------------------------------------------------------
# STEP 7: Save Calibrated Model
# ---------------------------------------------------------------------------

def save_calibrated_model(profile, expected, step_ms=100,
                          filepath="outputs/calibrated_model.json"):
    """
    Run measurements, build a calibration report, and save the full
    calibrated model package to disk.

    Package schema:
    {
      "profile":    {...},   # the calibrated profile
      "report":     {...},   # calibration report (score, per-parameter errors)
      "expected":   {...},   # real-world target values used for calibration
      "step_ms":    int
    }

    Args:
        profile  : dict — calibrated profile (from calibrate() or manual)
        expected : dict — real-world target measurements
        step_ms  : int  — simulation tick size
        filepath : str  — output JSON path

    Returns:
        dict — the saved package
    """
    measured = measure_twin(profile, step_ms)
    report   = build_calibration_report(profile, measured, expected)

    package = {
        "profile":  profile,
        "report":   report,
        "expected": expected,
        "step_ms":  step_ms
    }

    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath)
                else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(package, f, indent=2)

    return package


def load_calibrated_model(filepath):
    """
    Load a previously saved calibrated model package.

    Returns:
        dict — package with keys: profile, report, expected, step_ms
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# STEP 8: Validation Scenarios
# ---------------------------------------------------------------------------

def run_validation_scenarios(profile, scenarios, step_ms=100):
    """
    Run a list of validation scenarios against a calibrated profile.

    Each scenario defines:
      - name        : str
      - expected    : dict of measurement targets
      - tolerance   : float — acceptable relative error % per parameter

    Args:
        profile   : dict — calibration profile to validate
        scenarios : list of scenario dicts
        step_ms   : int  — simulation tick size

    Returns:
        list of result dicts:
        [
          {
            "scenario":  str,
            "passed":    bool,
            "score":     float,
            "tolerance": float,
            "failures":  [str, ...]   # parameters outside tolerance
          }
        ]
    """
    results = []

    for scenario in scenarios:
        name      = scenario["name"]
        expected  = scenario["expected"]
        tolerance = scenario.get("tolerance", 5.0)

        measured = measure_twin(profile, step_ms)
        errors   = calculate_errors(measured, expected)
        score    = total_error_score(errors)

        failures = [
            f"{key}: expected={e['expected']} simulated={e['measured']} "
            f"error={e['relative_error_pct']}% > {tolerance}%"
            for key, e in errors.items()
            if e["relative_error_pct"] is not None
            and e["relative_error_pct"] > tolerance
        ]

        results.append({
            "scenario":  name,
            "passed":    len(failures) == 0,
            "score":     score,
            "tolerance": tolerance,
            "failures":  failures
        })

    return results


def print_validation_results(results):
    """Print validation scenario results."""
    print("=" * 60)
    print("  VALIDATION RESULTS")
    print("=" * 60)
    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}]  {r['scenario']}  "
              f"(score={r['score']}%, tolerance={r['tolerance']}%)")
        for f in r["failures"]:
            print(f"           ✗ {f}")
    print("-" * 60)
    print(f"  Total: {total}  Passed: {passed}  Failed: {total - passed}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# STEP 9: Drift Detection
# ---------------------------------------------------------------------------

def create_baseline(profile, step_ms=100):
    """
    Measure a profile and store the result as a baseline snapshot.

    Returns:
        dict — {"measurements": {...}, "profile_name": str}
    """
    measurements = measure_twin(profile, step_ms)
    return {
        "profile_name": profile.get("name", "unknown"),
        "measurements": measurements
    }


def detect_drift(current_measurements, baseline, drift_threshold_pct=5.0):
    """
    Compare current measurements against a baseline and detect drift.

    A parameter is considered drifted if:
      |current - baseline| / baseline > drift_threshold_pct / 100

    Args:
        current_measurements : dict — output of measure_twin()
        baseline             : dict — output of create_baseline()
        drift_threshold_pct  : float — % change that counts as drift

    Returns:
        {
          "drifted":    bool,
          "threshold":  float,
          "drifts": [
            {
              "parameter":    str,
              "baseline":     float,
              "current":      float,
              "change_pct":   float,
              "direction":    "UP" | "DOWN"
            }
          ],
          "stable": [str, ...]   # parameters within threshold
        }
    """
    baseline_meas = baseline["measurements"]
    drifts  = []
    stable  = []

    for key, baseline_val in baseline_meas.items():
        current_val = current_measurements.get(key)

        if baseline_val is None or current_val is None:
            continue

        if baseline_val == 0:
            change_pct = 0.0 if current_val == 0 else 100.0
        else:
            change_pct = abs(current_val - baseline_val) / baseline_val * 100

        change_pct = round(change_pct, 2)

        if change_pct > drift_threshold_pct:
            drifts.append({
                "parameter":  key,
                "baseline":   baseline_val,
                "current":    current_val,
                "change_pct": change_pct,
                "direction":  "UP" if current_val > baseline_val else "DOWN"
            })
        else:
            stable.append(key)

    return {
        "drifted":   len(drifts) > 0,
        "threshold": drift_threshold_pct,
        "drifts":    drifts,
        "stable":    stable
    }


def print_drift_report(drift_result, baseline_name=""):
    """Print drift detection results."""
    label = f" (baseline: {baseline_name})" if baseline_name else ""
    print("=" * 60)
    print(f"  DRIFT DETECTION REPORT{label}")
    print("=" * 60)
    print(f"  Threshold : {drift_result['threshold']}%")
    print(f"  Drifted   : {drift_result['drifted']}")

    if drift_result["drifts"]:
        print(f"\n  Drifted parameters ({len(drift_result['drifts'])}):")
        print(f"  {'Parameter':<30}  {'Baseline':>10}  {'Current':>10}  "
              f"{'Change%':>8}  {'Dir':>5}")
        print("  " + "-" * 68)
        for d in drift_result["drifts"]:
            print(f"  {d['parameter']:<30}  {d['baseline']:>10}  "
                  f"{d['current']:>10}  {d['change_pct']:>7.2f}%  "
                  f"{d['direction']:>5}")

    if drift_result["stable"]:
        print(f"\n  Stable parameters: {drift_result['stable']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# STEP 10: Calibration Summary
# ---------------------------------------------------------------------------

def calibration_summary(initial_profile, calibrated_profile, expected,
                        step_ms=100, drift_threshold_pct=5.0):
    """
    Run the full calibration pipeline and produce a comprehensive summary.

    Includes:
      - Initial vs calibrated accuracy
      - Per-parameter improvement
      - Drift status vs baseline
      - Overall accuracy rating

    Args:
        initial_profile    : dict — starting profile (before calibration)
        calibrated_profile : dict — profile after calibration
        expected           : dict — real-world target measurements
        step_ms            : int  — simulation tick size
        drift_threshold_pct: float — drift detection threshold

    Returns:
        dict — full summary
    """
    # Measure both profiles
    initial_measured    = measure_twin(initial_profile,    step_ms)
    calibrated_measured = measure_twin(calibrated_profile, step_ms)

    # Error scores
    initial_errors    = calculate_errors(initial_measured,    expected)
    calibrated_errors = calculate_errors(calibrated_measured, expected)
    initial_score     = total_error_score(initial_errors)
    calibrated_score  = total_error_score(calibrated_errors)

    improvement = round(initial_score - calibrated_score, 2) \
                  if (initial_score is not None and calibrated_score is not None) \
                  else None

    # Per-parameter improvement
    parameter_improvements = []
    for key in expected:
        i_err = initial_errors.get(key, {})
        c_err = calibrated_errors.get(key, {})
        i_pct = i_err.get("relative_error_pct")
        c_pct = c_err.get("relative_error_pct")
        delta = round(i_pct - c_pct, 2) if (i_pct is not None and
                                              c_pct is not None) else None
        parameter_improvements.append({
            "parameter":        key,
            "initial_error_pct":    i_pct,
            "calibrated_error_pct": c_pct,
            "improvement_pct":      delta
        })

    # Drift check: calibrated vs initial baseline
    baseline   = create_baseline(initial_profile, step_ms)
    drift      = detect_drift(calibrated_measured, baseline, drift_threshold_pct)

    # Accuracy rating
    if calibrated_score is None:
        rating = "UNKNOWN"
    elif calibrated_score <= 1.0:
        rating = "EXCELLENT"
    elif calibrated_score <= 5.0:
        rating = "GOOD"
    elif calibrated_score <= 10.0:
        rating = "ACCEPTABLE"
    else:
        rating = "NEEDS TUNING"

    return {
        "initial_profile":    initial_profile.get("name"),
        "calibrated_profile": calibrated_profile.get("name"),
        "initial_score":      initial_score,
        "calibrated_score":   calibrated_score,
        "improvement":        improvement,
        "rating":             rating,
        "parameter_improvements": parameter_improvements,
        "drift":              drift
    }


def print_calibration_summary(summary):
    """Print the full calibration summary."""
    print("=" * 60)
    print("  CALIBRATION SUMMARY")
    print("=" * 60)
    print(f"  Initial profile    : {summary['initial_profile']}")
    print(f"  Calibrated profile : {summary['calibrated_profile']}")
    print(f"  Initial score      : {summary['initial_score']}%")
    print(f"  Calibrated score   : {summary['calibrated_score']}%")
    print(f"  Improvement        : {summary['improvement']}%")
    print(f"  Accuracy rating    : {summary['rating']}")

    print(f"\n  Per-parameter improvement:")
    print(f"  {'Parameter':<30}  {'Initial%':>9}  {'Calibrated%':>12}  "
          f"{'Δ':>8}")
    print("  " + "-" * 64)
    for p in summary["parameter_improvements"]:
        i   = f"{p['initial_error_pct']}%"    if p['initial_error_pct']    is not None else "N/A"
        c   = f"{p['calibrated_error_pct']}%" if p['calibrated_error_pct'] is not None else "N/A"
        imp = f"{p['improvement_pct']}%"       if p['improvement_pct']      is not None else "N/A"
        print(f"  {p['parameter']:<30}  {i:>9}  {c:>12}  {imp:>8}")

    d = summary["drift"]
    print(f"\n  Drift vs initial baseline (threshold={d['threshold']}%):")
    if d["drifted"]:
        for dr in d["drifts"]:
            print(f"    ⚠ {dr['parameter']}: {dr['change_pct']}% {dr['direction']}")
    else:
        print("    ✓ No significant drift detected")
    print("=" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 9 - Step 10: Calibration Summary")
    print("=" * 60)

    REAL_WORLD = {
        "motor_start_delay_ms":      280,
        "motor_stop_delay_ms":       190,
        "cycle_time_ms":             3500,
        "sensor_trigger_time_ms":    1650,
        "sensor_active_duration_ms": 195,
    }

    # -------------------------------------------------------
    # Run full calibration pipeline
    # -------------------------------------------------------
    print("\nRunning calibration loop...")
    cal_result = calibrate(DEFAULT_PROFILE, REAL_WORLD,
                           step_ms=100, max_iterations=20,
                           tolerance_pct=1.0, verbose=False)

    calibrated = cal_result["profile"]
    calibrated["name"] = "calibrated"

    # -------------------------------------------------------
    # Build and print summary
    # -------------------------------------------------------
    summary = calibration_summary(
        initial_profile=DEFAULT_PROFILE,
        calibrated_profile=calibrated,
        expected=REAL_WORLD,
        step_ms=100,
        drift_threshold_pct=5.0
    )

    print_calibration_summary(summary)

    # -------------------------------------------------------
    # Save summary to JSON
    # -------------------------------------------------------
    summary_path = "outputs/calibration_summary.json"
    # Remove non-serialisable items (drift contains nested dicts — already clean)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n  Summary saved to: {summary_path}")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Required keys
    for key in ("initial_profile", "calibrated_profile", "initial_score",
                "calibrated_score", "improvement", "rating",
                "parameter_improvements", "drift"):
        assert key in summary, f"missing key: {key}"
    print("  PASS — summary has all required keys")

    # Calibrated score ≤ initial score
    assert summary["calibrated_score"] <= summary["initial_score"], \
        f"calibrated must be ≤ initial: {summary['calibrated_score']} vs {summary['initial_score']}"
    print(f"  PASS — calibrated ({summary['calibrated_score']}%) "
          f"≤ initial ({summary['initial_score']}%)")

    # Improvement is non-negative
    assert summary["improvement"] >= 0, \
        f"improvement must be ≥ 0, got {summary['improvement']}"
    print(f"  PASS — improvement={summary['improvement']}% (non-negative)")

    # Rating is a valid string
    valid_ratings = {"EXCELLENT", "GOOD", "ACCEPTABLE", "NEEDS TUNING", "UNKNOWN"}
    assert summary["rating"] in valid_ratings, \
        f"invalid rating: {summary['rating']}"
    print(f"  PASS — rating='{summary['rating']}' (valid)")

    # Parameter improvements list has correct length
    assert len(summary["parameter_improvements"]) == len(REAL_WORLD)
    print(f"  PASS — {len(summary['parameter_improvements'])} parameter entries")

    # File saved
    assert os.path.exists(summary_path)
    print(f"  PASS — {summary_path} saved to disk")
