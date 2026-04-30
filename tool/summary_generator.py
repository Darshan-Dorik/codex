"""
tool/summary_generator.py — Human-Readable Summary Generator

Converts technical pipeline results into a concise, operator-friendly
summary printed to the console.

Design principles:
  - No jargon — plain English
  - Most important information first
  - Failures and violations highlighted clearly
  - Fits in a terminal window (≤ 80 chars wide)
"""

import os


def generate_summary(pipeline_result, config, run_dir=None):
    """
    Generate a human-readable summary from a pipeline result.

    Args:
        pipeline_result : dict — from run_pipeline()
        config          : dict — the config used
        run_dir         : str | None — output directory path

    Returns:
        str — formatted summary text
    """
    lines = []
    sep   = "=" * 60

    lines.append(sep)
    lines.append("  VALIDATION SUMMARY")
    lines.append(sep)

    # --- Status ---
    status = pipeline_result.get("status", "unknown")
    if status == "error":
        lines.append(f"  STATUS   : ❌  ERROR")
        lines.append(f"  REASON   : {pipeline_result.get('error', 'unknown')}")
        lines.append(sep)
        return "\n".join(lines)

    lines.append(f"  STATUS   : ✓  COMPLETED")
    lines.append(f"  Program  : {pipeline_result.get('program', '?')}")
    if run_dir:
        lines.append(f"  Output   : {run_dir}")
    lines.append("")

    # --- Scenario results ---
    agg  = pipeline_result.get("aggregation", {})
    total      = agg.get("total_runs",  0)
    passed     = agg.get("passed",      0)
    failed     = agg.get("failed",      0)
    errors     = agg.get("errors",      0)
    violations = agg.get("violations",  0)

    lines.append("  Scenarios")
    lines.append(f"    Run      : {total}")
    lines.append(f"    Passed   : {passed}")
    if failed:
        lines.append(f"    Failed   : {failed}  ⚠")
    else:
        lines.append(f"    Failed   : {failed}")
    if errors:
        lines.append(f"    Errors   : {errors}  ⚠")

    # --- Violations ---
    lines.append("")
    lines.append("  Safety Properties")
    if violations == 0:
        lines.append("    No violations detected  ✓")
    else:
        lines.append(f"    {violations} violation(s) detected  ⚠")
        vsummary = agg.get("violation_summary", {})
        for prop, data in vsummary.items():
            lines.append(f"    • {prop}")
            lines.append(f"      {data['count']} time(s) in: "
                         f"{data['scenarios']}")

    # --- Failures detail ---
    failures = agg.get("failures", [])
    if failures:
        lines.append("")
        lines.append("  Failures")
        for f in failures[:5]:   # show max 5
            lines.append(f"    [{f['status'].upper()}] {f['scenario']}")
            for err in f.get("errors", [])[:2]:
                lines.append(f"      • {err}")
            for v in f.get("violations", [])[:2]:
                lines.append(f"      ⚠ t={v['time']}ms: {v['property']}")
        if len(failures) > 5:
            lines.append(f"    ... and {len(failures) - 5} more")

    # --- Calibration ---
    cal = pipeline_result.get("calibration")
    if cal:
        lines.append("")
        lines.append("  Calibration")
        score = cal.get("score")
        if score is not None:
            rating = ("EXCELLENT" if score <= 1 else
                      "GOOD"      if score <= 5 else
                      "ACCEPTABLE" if score <= 10 else
                      "NEEDS TUNING")
            lines.append(f"    Profile  : {cal.get('profile_name', '?')}")
            lines.append(f"    Score    : {score}%  [{rating}]")
            # Show worst parameter
            cal_errors = cal.get("errors", {})
            if cal_errors:
                worst = max(cal_errors.items(),
                            key=lambda x: x[1].get("error_pct") or 0)
                lines.append(f"    Worst    : {worst[0]} "
                             f"({worst[1].get('error_pct')}% error)")

    # --- AI analysis ---
    ai = pipeline_result.get("ai_report")
    if ai:
        lines.append("")
        lines.append("  AI Analysis")
        meta = ai.get("meta", {})
        lines.append(f"    Gaps     : {meta.get('has_gaps', False)}")
        lines.append(f"    Skipped  : {meta.get('any_skipped', True)}")
        fa = ai.get("failure_analysis", "")
        if fa and not fa.startswith("[SKIPPED]"):
            # Show first sentence only
            first_sentence = fa.split(".")[0].strip()
            lines.append(f"    Insight  : {first_sentence[:70]}...")

    # --- Overall verdict ---
    lines.append("")
    lines.append(sep)
    if failed == 0 and violations == 0 and errors == 0:
        lines.append("  RESULT   : ✓  ALL CHECKS PASSED")
    elif violations > 0:
        lines.append("  RESULT   : ⚠  SAFETY VIOLATIONS DETECTED")
    elif failed > 0:
        lines.append("  RESULT   : ⚠  SOME SCENARIOS FAILED")
    else:
        lines.append("  RESULT   : ⚠  ERRORS ENCOUNTERED")
    lines.append(sep)

    return "\n".join(lines)


def print_summary(pipeline_result, config, run_dir=None):
    """Print the human-readable summary to stdout."""
    print(generate_summary(pipeline_result, config, run_dir))


if __name__ == "__main__":
    import sys
    import json

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _subdir in ("", "src/core", "src/testing", "src/batch",
                    "src/analysis", "src/ai", "tool"):
        _p = os.path.join(_ROOT, _subdir)
        if _p not in sys.path:
            sys.path.insert(0, _p)

    from config_loader import load_config
    from orchestrator  import run_pipeline

    print("=" * 60)
    print("Phase 10 - Step 5: Human-Readable Summary Generator")
    print("=" * 60)

    config_path = "outputs/test_config.json"
    config = load_config(config_path)

    # -------------------------------------------------------
    # Test 1: successful run — no failures
    # -------------------------------------------------------
    print("\nTest 1 — Successful run (no failures):")
    result1 = run_pipeline(config, verbose=False)
    print_summary(result1, config, run_dir="outputs/runs/test_run/20260430_120000")

    # -------------------------------------------------------
    # Test 2: run with violations (shuttle_control.st)
    # -------------------------------------------------------
    print("\nTest 2 — Run with safety violations:")
    config2 = dict(config)
    config2["program"] = "programs/shuttle_control.st"
    # Use a scenario that triggers the safety property
    from scenario_template import expand_template
    from batch_executor import execute_scenarios
    from st_loader import load_st_file
    from st_parser import parse_st
    from aggregator import aggregate_results
    from properties import make_property
    import io

    prop = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") and s["inputs"].get("X1"))
    )
    scenarios = expand_template({
        "name": "ViolationTest",
        "inputs": ["X0", "X1", "X2"],
        "timing": [300],
        "variations": [
            {"__initial__": {"X0": True}, "X0": True, "X1": True, "X2": False}
        ],
        "expected": []
    })
    logic2 = parse_st(load_st_file("programs/shuttle_control.st"))
    old_stdout = sys.stdout; sys.stdout = io.StringIO()
    results2 = execute_scenarios(scenarios, logic2, max_time_ms=500,
                                 step_ms=100, properties=[prop])
    sys.stdout = old_stdout

    result2 = {
        "status": "success",
        "program": "programs/shuttle_control.st",
        "scenarios_run": len(results2),
        "results": results2,
        "aggregation": aggregate_results(results2),
        "calibration": None,
        "ai_report": None
    }
    print_summary(result2, config2)

    # -------------------------------------------------------
    # Test 3: error result
    # -------------------------------------------------------
    print("\nTest 3 — Error result:")
    error_result = {
        "status": "error",
        "error":  "ST file not found: programs/missing.st",
        "program": "programs/missing.st",
        "scenarios_run": 0,
        "results": [], "aggregation": {},
        "calibration": None, "ai_report": None
    }
    print_summary(error_result, config)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    s1 = generate_summary(result1, config)
    assert "ALL CHECKS PASSED" in s1,       "clean run must say ALL CHECKS PASSED"
    assert "COMPLETED"         in s1,       "must show COMPLETED status"
    print("  PASS — clean run: 'ALL CHECKS PASSED'")

    s2 = generate_summary(result2, config2)
    assert "SAFETY VIOLATIONS" in s2,       "violations must be highlighted"
    assert "violation(s)"      in s2,       "violation count must appear"
    print("  PASS — violation run: 'SAFETY VIOLATIONS DETECTED'")

    s3 = generate_summary(error_result, config)
    assert "ERROR"             in s3,       "error result must show ERROR"
    assert "missing.st"        in s3,       "error message must appear"
    print("  PASS — error result: shows ERROR with reason")

    # Summary is a non-empty string
    assert len(s1) > 100,                   "summary must be non-trivial"
    print("  PASS — summary is non-trivial string")
