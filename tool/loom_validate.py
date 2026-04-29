"""
tool/loom_validate.py — CLI Entry Point

Usage:
    python tool/loom_validate.py config.json
    python tool/loom_validate.py config.json --dry-run
    python tool/loom_validate.py --template > my_config.json

Commands:
    config.json          Run full validation pipeline
    --dry-run            Validate config only, no simulation
    --template           Print a starter config template to stdout
    --help               Show usage
"""

import sys
import os
import json
import argparse

# Ensure tool/ and project root are on the path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOL = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, _TOOL):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tool.config_loader import load_config, print_config_summary, ConfigError

# ---------------------------------------------------------------------------
# Config template
# ---------------------------------------------------------------------------

CONFIG_TEMPLATE = {
    "program":    "programs/motor_start.st",
    "output_dir": "outputs/runs/my_run",
    "calibration": None,
    "scenarios": {
        "inputs":        ["X0", "X1"],
        "timing":        [300, 600],
        "max_scenarios": 8,
        "step_ms":       100
    },
    "real_world": {
        "motor_start_delay_ms":      300,
        "motor_stop_delay_ms":       200,
        "cycle_time_ms":             3600,
        "sensor_trigger_time_ms":    1800,
        "sensor_active_duration_ms": 200
    },
    "properties": [
        {
            "name":  "Y0 must not be True when X1 is True",
            "check": "lambda s: not (s['outputs'].get('Y0') and s['inputs'].get('X1'))"
        }
    ],
    "ai_analysis": False
}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="loom-validate",
        description="PLC Loom Validation Tool — run full validation from a config file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tool/loom_validate.py config.json
  python tool/loom_validate.py config.json --dry-run
  python tool/loom_validate.py --template > my_config.json
        """
    )
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to config.json"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config only — do not run simulation"
    )
    parser.add_argument(
        "--template",
        action="store_true",
        help="Print a starter config template to stdout"
    )
    return parser.parse_args(argv)


def main(argv=None):
    """
    Main entry point.

    Returns:
        int — exit code (0 = success, 1 = error)
    """
    args = parse_args(argv)

    # --- Template mode ---
    if args.template:
        print(json.dumps(CONFIG_TEMPLATE, indent=2))
        return 0

    # --- Require config path for all other modes ---
    if not args.config:
        print("ERROR: config file path required.")
        print("Usage: python tool/loom_validate.py config.json")
        print("       python tool/loom_validate.py --template")
        return 1

    # --- Load and validate config ---
    print(f"loom-validate  config={args.config}")
    print("-" * 50)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"CONFIG ERROR: {e}")
        return 1

    print_config_summary(config)

    # --- Dry-run mode: stop here ---
    if args.dry_run:
        print("\n[DRY RUN] Config is valid. No simulation will be run.")
        return 0

    # --- Full pipeline (Steps 3-10 will plug in here) ---
    print("\n[INFO] Config loaded successfully.")
    print("[INFO] Full pipeline not yet implemented — coming in Step 3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
