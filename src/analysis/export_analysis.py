"""
export_analysis.py — Export Analysis Package

Runs the full validation pipeline for a given ST program and
saves a structured analysis.json file.

Pipeline:
  1. Load + parse ST file
  2. Generate scenarios from template
  3. Execute all scenarios (with properties)
  4. Aggregate failures + violations
  5. Detect coverage gaps
  6. Compress logs around failures/violations
  7. Build structured payload
  8. Save to analysis.json
"""

import json
import os

from st_loader import load_st_file
from st_parser import parse_st
from batch_executor import execute_scenarios
from analysis_payload import build_analysis_payload
from log_filter import compress_result_logs


def export_analysis_package(
    st_file,
    scenarios,
    properties=None,
    max_time_ms=1000,
    step_ms=100,
    wiring=None,
    log_window_before_ms=200,
    log_window_after_ms=200,
    output_path="analysis.json"
):
    """
    Run the full validation pipeline and export analysis.json.

    Args:
        st_file              : str  — path to .st file
        scenarios            : list — scenario dicts to run
        properties           : list — property dicts (optional)
        max_time_ms          : int  — simulation duration per scenario
        step_ms              : int  — tick size
        wiring               : callable — optional loom wiring callback
        log_window_before_ms : int  — ms before each focus time to keep
        log_window_after_ms  : int  — ms after each focus time to keep
        output_path          : str  — output JSON file path

    Returns:
        dict — the full analysis package (also saved to output_path)
    """
    # 1. Load + parse
    st_code = load_st_file(st_file)
    logic   = parse_st(st_code)

    # 2. Execute all scenarios
    results = execute_scenarios(
        scenarios, logic,
        max_time_ms=max_time_ms,
        step_ms=step_ms,
        wiring=wiring,
        properties=properties or []
    )

    # 3. Build structured payload (failures, gaps, violations, summary)
    payload = build_analysis_payload(st_file, results)

    # 4. Attach compressed logs for each scenario that has failures/violations
    compressed_logs = []
    for r in results:
        has_issues = bool(r["violations"] or r["errors"] or r["status"] == "error")
        compressed = compress_result_logs(
            r,
            window_before_ms=log_window_before_ms,
            window_after_ms=log_window_after_ms
        )
        if has_issues or compressed["kept_ticks"] > 0:
            compressed_logs.append({
                "scenario":      r["scenario"],
                "has_issues":    has_issues,
                "compressed_log": compressed
            })

    payload["compressed_logs"] = compressed_logs

    # 5. Save to file
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path)
                else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return payload


if __name__ == "__main__":
    from scenario_generator import generate_scenarios
    from scenario_template import expand_template
    from properties import make_property

    print("=" * 60)
    print("Phase 5 - Step 10: Export Analysis Package")
    print("=" * 60)

    prop_safety = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X1") is True)
    )

    # -------------------------------------------------------
    # Package A: motor_start.st — full coverage, no violations
    # -------------------------------------------------------
    print("\n--- Package A: motor_start.st ---")
    gen_a = generate_scenarios(
        inputs=["X0", "X1"], timing=[300], max_scenarios=4, base_name="Motor"
    )
    pkg_a = export_analysis_package(
        st_file="programs/motor_start.st",
        scenarios=gen_a["scenarios"],
        properties=[prop_safety],
        max_time_ms=500,
        step_ms=100,
        output_path="analysis_motor.json"
    )
    print(f"  Saved: analysis_motor.json")
    print(f"  Summary: {pkg_a['summary']}")
    print(f"  Compressed logs: {len(pkg_a['compressed_logs'])} scenario(s) with issues")

    # -------------------------------------------------------
    # Package B: shuttle_control.st — violations + gap
    # -------------------------------------------------------
    print("\n--- Package B: shuttle_control.st ---")
    shuttle_scenarios = expand_template({
        "name": "Shuttle",
        "inputs": ["X0", "X1", "X2"],
        "timing": [300],
        "variations": [
            {"X0": True,  "X1": False, "X2": False},   # normal run
            {"__initial__": {"X0": True},
             "X0": True, "X1": True, "X2": False},     # fault while running
        ],
        "expected": []
    })
    pkg_b = export_analysis_package(
        st_file="programs/shuttle_control.st",
        scenarios=shuttle_scenarios,
        properties=[prop_safety],
        max_time_ms=500,
        step_ms=100,
        log_window_before_ms=100,
        log_window_after_ms=100,
        output_path="analysis_shuttle.json"
    )
    print(f"  Saved: analysis_shuttle.json")
    print(f"  Summary: {pkg_b['summary']}")
    print(f"  Compressed logs: {len(pkg_b['compressed_logs'])} scenario(s) with issues")

    # -------------------------------------------------------
    # Print full JSON for Package B
    # -------------------------------------------------------
    print("\n--- analysis_shuttle.json (full) ---")
    print(json.dumps(pkg_b, indent=2))

    # -------------------------------------------------------
    # Verify file structure
    # -------------------------------------------------------
    print("\n--- File Verification ---")

    for fname in ("analysis_motor.json", "analysis_shuttle.json"):
        assert os.path.exists(fname), f"{fname} not found"
        with open(fname) as f:
            loaded = json.load(f)
        required_keys = {"program", "summary", "failures",
                         "coverage_gaps", "violations", "compressed_logs"}
        missing = required_keys - set(loaded.keys())
        assert not missing, f"{fname} missing keys: {missing}"
        print(f"  PASS — {fname}: valid JSON, all required keys present")

    # -------------------------------------------------------
    # Assertions on content
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Package A: clean run
    assert pkg_a["summary"]["violations"] == 0,     "A: no violations"
    assert pkg_a["summary"]["has_gaps"]   is False,  "A: no gaps"
    assert len(pkg_a["compressed_logs"])  == 0,     "A: no compressed logs (no issues)"
    print("  PASS — Package A: no violations, no gaps, no compressed logs")

    # Package B: violations present, both branches covered across 2 scenarios
    assert pkg_b["summary"]["violations"] > 0,      "B: violations expected"
    # Both scenarios together cover all branches — no gap (correct behavior)
    assert pkg_b["summary"]["has_gaps"]   is False,  "B: 2 scenarios cover all branches"
    assert len(pkg_b["compressed_logs"])  > 0,      "B: compressed logs present"
    # Compressed log entries only cover the violation window
    for cl in pkg_b["compressed_logs"]:
        assert cl["compressed_log"]["kept_ticks"] <= \
               cl["compressed_log"]["total_ticks"], "kept <= total"
    print(f"  PASS — Package B: {pkg_b['summary']['violations']} violations, "
          f"no gaps (2 scenarios cover all branches), "
          f"{len(pkg_b['compressed_logs'])} compressed log(s)")

    # Summary structure
    for key in ("total_runs", "passed", "failed", "errors",
                "violations", "has_gaps"):
        assert key in pkg_b["summary"], f"summary missing key: {key}"
    print("  PASS — Summary has all required keys")
