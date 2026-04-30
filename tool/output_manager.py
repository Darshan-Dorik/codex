"""
tool/output_manager.py — Output Directory Manager

Creates a timestamped output folder for each run and saves:
  - report.json       : full pipeline result
  - ai_report.json    : AI analysis (if enabled)
  - run_config.json   : copy of the config used

Folder structure:
  <output_dir>/
    <YYYYMMDD_HHMMSS>/
      report.json
      ai_report.json    (optional)
      run_config.json
"""

import json
import os
from datetime import datetime


def create_run_dir(base_dir):
    """
    Create a timestamped subdirectory inside base_dir.

    Args:
        base_dir : str — base output directory from config

    Returns:
        str — path to the created run directory
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir   = os.path.join(base_dir, timestamp)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def save_run_outputs(run_dir, pipeline_result, config):
    """
    Save all run outputs to the run directory.

    Args:
        run_dir         : str  — path from create_run_dir()
        pipeline_result : dict — from run_pipeline()
        config          : dict — the config used for this run

    Returns:
        dict — {"report": path, "ai_report": path | None,
                "run_config": path}
    """
    saved = {}

    # --- report.json: full pipeline result (without raw timelines) ---
    report_data = _build_report(pipeline_result)
    report_path = os.path.join(run_dir, "report.json")
    _write_json(report_path, report_data)
    saved["report"] = report_path

    # --- ai_report.json: AI analysis (if present) ---
    ai_report = pipeline_result.get("ai_report")
    if ai_report:
        ai_path = os.path.join(run_dir, "ai_report.json")
        # Remove non-serialisable callables if any
        ai_serialisable = {
            k: v for k, v in ai_report.items()
            if k != "prompts"   # prompts saved separately if needed
        }
        _write_json(ai_path, ai_serialisable)
        saved["ai_report"] = ai_path
    else:
        saved["ai_report"] = None

    # --- run_config.json: copy of config ---
    config_path = os.path.join(run_dir, "run_config.json")
    _write_json(config_path, config)
    saved["run_config"] = config_path

    return saved


def _build_report(pipeline_result):
    """
    Build a clean, serialisable report from the pipeline result.
    Strips raw timelines to keep file size small.
    """
    agg = pipeline_result.get("aggregation", {})

    # Strip timelines from individual results
    clean_results = []
    for r in pipeline_result.get("results", []):
        clean_results.append({
            "scenario":   r.get("scenario"),
            "status":     r.get("status"),
            "errors":     r.get("errors", []),
            "violations": r.get("violations", []),
            "error_msg":  r.get("error_msg")
        })

    return {
        "status":        pipeline_result.get("status"),
        "program":       pipeline_result.get("program"),
        "scenarios_run": pipeline_result.get("scenarios_run", 0),
        "summary": {
            "total_runs": agg.get("total_runs", 0),
            "passed":     agg.get("passed",     0),
            "failed":     agg.get("failed",     0),
            "errors":     agg.get("errors",     0),
            "violations": agg.get("violations", 0),
        },
        "failures":      agg.get("failures",          []),
        "violation_summary": agg.get("violation_summary", {}),
        "calibration":   pipeline_result.get("calibration"),
        "scenarios":     clean_results
    }


def _write_json(path, data):
    """Write data as indented JSON to path."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def print_output_summary(run_dir, saved):
    """Print a summary of saved output files."""
    print(f"  Output directory : {run_dir}")
    for key, path in saved.items():
        if path:
            size = os.path.getsize(path)
            print(f"    {key:<15} : {os.path.basename(path)}  ({size} bytes)")
        else:
            print(f"    {key:<15} : (not generated)")


if __name__ == "__main__":
    import sys

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _subdir in ("", "src/core", "src/testing", "src/batch",
                    "src/analysis", "src/ai", "tool"):
        _p = os.path.join(_ROOT, _subdir)
        if _p not in sys.path:
            sys.path.insert(0, _p)

    from config_loader import load_config
    from orchestrator  import run_pipeline

    print("=" * 60)
    print("Phase 10 - Step 4: Output Directory Manager")
    print("=" * 60)

    config_path = "outputs/test_config.json"
    if not os.path.exists(config_path):
        print(f"  {config_path} not found")
        sys.exit(1)

    config = load_config(config_path)

    # Run pipeline
    print("\nRunning pipeline...")
    result = run_pipeline(config, verbose=False)

    # Create run directory and save outputs
    run_dir = create_run_dir(config["output_dir"])
    saved   = save_run_outputs(run_dir, result, config)

    print(f"\nOutputs saved:")
    print_output_summary(run_dir, saved)

    # Show report.json structure
    print("\n--- report.json (top-level keys) ---")
    with open(saved["report"]) as f:
        report = json.load(f)
    for key, val in report.items():
        if isinstance(val, (dict, list)):
            print(f"  {key}: {type(val).__name__} "
                  f"({len(val)} item(s))")
        else:
            print(f"  {key}: {val}")

    # --- Assertions ---
    print("\n--- Assertions ---")

    assert os.path.isdir(run_dir),              "run directory must exist"
    print(f"  PASS — run directory created: {run_dir}")

    assert os.path.exists(saved["report"]),     "report.json must exist"
    assert os.path.exists(saved["run_config"]), "run_config.json must exist"
    print("  PASS — report.json and run_config.json saved")

    assert saved["ai_report"] is None,          "AI disabled → no ai_report.json"
    print("  PASS — ai_report.json not created (AI disabled)")

    # report.json has required keys
    for key in ("status", "program", "scenarios_run", "summary",
                "scenarios", "calibration"):
        assert key in report, f"missing key in report: {key}"
    print("  PASS — report.json has all required keys")

    # run_config.json matches original config
    with open(saved["run_config"]) as f:
        saved_cfg = json.load(f)
    assert saved_cfg["program"] == config["program"]
    print("  PASS — run_config.json matches original config")

    # Timelines stripped from scenarios
    for s in report["scenarios"]:
        assert "timeline" not in s, "timelines must be stripped from report"
    print("  PASS — raw timelines stripped from report.json")
