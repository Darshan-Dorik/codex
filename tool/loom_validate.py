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

from tool.config_loader import load_config, print_config_summary

# ---------------------------------------------------------------------------
# Preset management
# ---------------------------------------------------------------------------

PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")


def list_presets():
    """Return list of (name, description) for all preset configs."""
    presets = []
    if not os.path.isdir(PRESETS_DIR):
        return presets
    for fname in sorted(os.listdir(PRESETS_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(PRESETS_DIR, fname)
            try:
                with open(path) as f:
                    data = json.load(f)
                name = fname[:-5]   # strip .json
                desc = data.get("_description", "(no description)")
                presets.append({"name": name, "description": desc, "path": path})
            except Exception:
                pass
    return presets


def get_preset_path(name):
    """
    Resolve a preset name to its file path.
    Accepts either a bare name (e.g. 'quick_check') or full path.
    """
    if os.path.exists(name):
        return name
    candidate = os.path.join(PRESETS_DIR, f"{name}.json")
    if os.path.exists(candidate):
        return candidate
    return None

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
    parser.add_argument(
        "--preset",
        metavar="NAME",
        help="Use a built-in preset config (use --list-presets to see options)"
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List all available preset configs"
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

    # --- List presets ---
    if args.list_presets:
        presets = list_presets()
        if not presets:
            print("No presets found.")
            return 0
        print("Available presets:")
        print(f"  {'Name':<30}  Description")
        print("  " + "-" * 60)
        for p in presets:
            print(f"  {p['name']:<30}  {p['description']}")
        return 0

    # --- Resolve preset to config path ---
    if args.preset:
        resolved = get_preset_path(args.preset)
        if not resolved:
            print(f"CONFIG ERROR: Preset '{args.preset}' not found. "
                  f"Use --list-presets to see options.")
            return 1
        args.config = resolved
        print(f"[INFO] Using preset: {args.preset}  ({resolved})")

    # --- Require config path for all other modes ---
    if not args.config:
        print("ERROR: config file path required.")
        print("Usage: python tool/loom_validate.py config.json")
        print("       python tool/loom_validate.py --template")
        return 1

    # --- Load and validate config ---
    print(f"loom-validate  config={args.config}")
    print("-" * 50)

    from tool.error_handler import safe_load_config
    config, err = safe_load_config(args.config)
    if err:
        print(err)
        return 1

    print_config_summary(config)

    # --- Dry-run mode: deep pre-flight checks ---
    if args.dry_run:
        from tool.dry_run import run_dry_run, print_dry_run_result
        result = run_dry_run(config)
        print()
        print_dry_run_result(result)
        return 0 if result["passed"] else 1

    # --- Full pipeline ---
    print("\n[INFO] Config loaded successfully. Starting pipeline...")
    print()

    from tool.orchestrator      import run_pipeline
    from tool.output_manager    import create_run_dir, save_run_outputs, \
                                        print_output_summary
    from tool.summary_generator import print_summary
    from tool.error_handler     import safe_run_pipeline

    result, err = safe_run_pipeline(config, verbose=True)
    print()
    if err:
        print(err)
        return 1

    # Save outputs
    run_dir = create_run_dir(config["output_dir"])
    saved   = save_run_outputs(run_dir, result, config)

    # Log the run
    from tool.run_logger import log_run
    config["_source_path"] = args.config
    log_run(config, result, run_dir=run_dir)

    # Human-readable summary
    print()
    print_summary(result, config, run_dir=run_dir)

    print()
    print_output_summary(run_dir, saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
