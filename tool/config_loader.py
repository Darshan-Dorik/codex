"""
tool/config_loader.py — Config Loader

Loads and validates a config.json file for the loom-validate tool.

Config schema:
{
  "program":       str,   # path to .st file
  "calibration":   str,   # path to calibration profile JSON (optional)
  "output_dir":    str,   # where to write run outputs
  "scenarios": {
    "inputs":        [str, ...],   # input variable names
    "timing":        [int, ...],   # event times in ms
    "max_scenarios": int,          # cap on generated scenarios
    "step_ms":       int           # simulation tick size
  },
  "real_world": {           # optional: real-world targets for calibration
    "<measurement>": float
  },
  "properties": [           # optional: safety properties
    {
      "name":  str,
      "check": str          # Python lambda expression as string
    }
  ],
  "ai_analysis": bool       # optional: run AI analysis (default false)
}
"""

import json
import os


# Required top-level fields and their expected types
_REQUIRED_FIELDS = {
    "program":    str,
    "output_dir": str,
    "scenarios":  dict,
}

# Required fields inside "scenarios"
_REQUIRED_SCENARIO_FIELDS = {
    "inputs":        list,
    "timing":        list,
    "max_scenarios": int,
    "step_ms":       int,
}


class ConfigError(Exception):
    """Raised when a config file is missing, malformed, or invalid."""
    pass


def load_config(filepath):
    """
    Load and validate a config.json file.

    Args:
        filepath : str — path to config JSON file

    Returns:
        dict — validated config

    Raises:
        ConfigError with a clear human-readable message on any problem
    """
    # --- File existence ---
    if not os.path.exists(filepath):
        raise ConfigError(f"Config file not found: {filepath}")

    # --- JSON parse ---
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config file is not valid JSON: {e}")

    if not isinstance(config, dict):
        raise ConfigError("Config must be a JSON object (dict)")

    # --- Required top-level fields ---
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in config:
            raise ConfigError(f"Missing required field: '{field}'")
        if not isinstance(config[field], expected_type):
            raise ConfigError(
                f"Field '{field}' must be {expected_type.__name__}, "
                f"got {type(config[field]).__name__}"
            )

    # --- Required scenario fields ---
    scenarios = config["scenarios"]
    for field, expected_type in _REQUIRED_SCENARIO_FIELDS.items():
        if field not in scenarios:
            raise ConfigError(f"Missing required field: 'scenarios.{field}'")
        if not isinstance(scenarios[field], expected_type):
            raise ConfigError(
                f"Field 'scenarios.{field}' must be "
                f"{expected_type.__name__}, "
                f"got {type(scenarios[field]).__name__}"
            )

    # --- Semantic checks ---
    if not scenarios["inputs"]:
        raise ConfigError("'scenarios.inputs' must not be empty")
    if not scenarios["timing"]:
        raise ConfigError("'scenarios.timing' must not be empty")
    if scenarios["max_scenarios"] < 1:
        raise ConfigError("'scenarios.max_scenarios' must be >= 1")
    if scenarios["step_ms"] < 1:
        raise ConfigError("'scenarios.step_ms' must be >= 1")

    # --- Optional field defaults ---
    config.setdefault("calibration",  None)
    config.setdefault("real_world",   {})
    config.setdefault("properties",   [])
    config.setdefault("ai_analysis",  False)

    return config


def print_config_summary(config):
    """Print a human-readable summary of a loaded config."""
    print("  Config loaded:")
    print(f"    program       : {config['program']}")
    print(f"    output_dir    : {config['output_dir']}")
    print(f"    calibration   : {config['calibration'] or '(none)'}")
    print(f"    inputs        : {config['scenarios']['inputs']}")
    print(f"    timing        : {config['scenarios']['timing']}")
    print(f"    max_scenarios : {config['scenarios']['max_scenarios']}")
    print(f"    step_ms       : {config['scenarios']['step_ms']}")
    print(f"    real_world    : {config['real_world'] or '(none)'}")
    print(f"    properties    : {len(config['properties'])} defined")
    print(f"    ai_analysis   : {config['ai_analysis']}")


if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Phase 10 - Step 1: Config Loader")
    print("=" * 60)

    # -------------------------------------------------------
    # Test 1: load a valid config
    # -------------------------------------------------------
    valid_config = {
        "program":    "programs/motor_start.st",
        "output_dir": "outputs/runs/test_run",
        "scenarios": {
            "inputs":        ["X0", "X1"],
            "timing":        [300, 600],
            "max_scenarios": 8,
            "step_ms":       100
        },
        "real_world": {
            "motor_start_delay_ms": 280,
            "cycle_time_ms":        3500
        },
        "properties": [
            {
                "name":  "Y0 must not be True when X1 is True",
                "check": "lambda s: not (s['outputs'].get('Y0') and s['inputs'].get('X1'))"
            }
        ],
        "ai_analysis": False
    }

    # Save to disk
    os.makedirs("outputs", exist_ok=True)
    valid_path = "outputs/test_config.json"
    with open(valid_path, "w") as f:
        json.dump(valid_config, f, indent=2)

    print(f"\nTest 1 — Load valid config ({valid_path}):")
    cfg = load_config(valid_path)
    print_config_summary(cfg)

    # -------------------------------------------------------
    # Test 2: missing required field
    # -------------------------------------------------------
    print("\nTest 2 — Missing 'program' field:")
    bad1 = {k: v for k, v in valid_config.items() if k != "program"}
    bad1_path = "outputs/test_config_bad1.json"
    with open(bad1_path, "w") as f:
        json.dump(bad1, f)
    try:
        load_config(bad1_path)
        print("  FAIL — should have raised ConfigError")
    except ConfigError as e:
        print(f"  ConfigError: {e}")

    # -------------------------------------------------------
    # Test 3: missing scenarios sub-field
    # -------------------------------------------------------
    print("\nTest 3 — Missing 'scenarios.step_ms':")
    bad2 = json.loads(json.dumps(valid_config))
    del bad2["scenarios"]["step_ms"]
    bad2_path = "outputs/test_config_bad2.json"
    with open(bad2_path, "w") as f:
        json.dump(bad2, f)
    try:
        load_config(bad2_path)
        print("  FAIL — should have raised ConfigError")
    except ConfigError as e:
        print(f"  ConfigError: {e}")

    # -------------------------------------------------------
    # Test 4: file not found
    # -------------------------------------------------------
    print("\nTest 4 — File not found:")
    try:
        load_config("outputs/nonexistent_config.json")
        print("  FAIL — should have raised ConfigError")
    except ConfigError as e:
        print(f"  ConfigError: {e}")

    # -------------------------------------------------------
    # Test 5: invalid JSON
    # -------------------------------------------------------
    print("\nTest 5 — Invalid JSON:")
    bad_json_path = "outputs/test_config_bad_json.json"
    with open(bad_json_path, "w") as f:
        f.write("{ this is not valid json }")
    try:
        load_config(bad_json_path)
        print("  FAIL — should have raised ConfigError")
    except ConfigError as e:
        print(f"  ConfigError: {e}")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Valid config loads correctly
    assert cfg["program"]                    == "programs/motor_start.st"
    assert cfg["scenarios"]["max_scenarios"] == 8
    assert cfg["ai_analysis"]               is False
    assert cfg["calibration"]               is None   # default applied
    print("  PASS — valid config loads with correct values and defaults")

    # All error cases raise ConfigError
    error_cases = [bad1_path, bad2_path, "nonexistent.json", bad_json_path]
    for path in error_cases:
        try:
            load_config(path)
            assert False, f"should have raised for {path}"
        except ConfigError:
            pass
    print("  PASS — all 4 error cases raise ConfigError with clear messages")

    # Defaults applied
    assert "calibration" in cfg
    assert "real_world"  in cfg
    assert "properties"  in cfg
    assert "ai_analysis" in cfg
    print("  PASS — optional fields have defaults applied")
