"""
batch_runner.py — Batch Program Runner

Runs multiple ST programs sequentially against a shared scenario,
collecting per-program results without modifying core execution logic.
"""

import json
from st_loader import load_st_file
from st_parser import parse_st
from test_harness import TestHarness


def run_batch(programs, scenario, max_time_ms=1000, step_ms=100,
              wiring=None, properties=None):
    """
    Run multiple ST programs sequentially against the same scenario.

    Args:
        programs    : list of {"name": str, "file": str}
        scenario    : scenario dict (initial_inputs, events, expected)
        max_time_ms : simulation duration per program
        step_ms     : tick size
        wiring      : optional wiring callback(plc, loom, t)
        properties  : optional list of property dicts

    Returns:
        list of result dicts:
        [
          {
            "name":       str,
            "file":       str,
            "status":     "pass" | "fail" | "error",
            "errors":     [...],
            "violations": [...],
            "error_msg":  str | None   # set only if status == "error"
          }
        ]
    """
    results = []

    for prog in programs:
        name = prog["name"]
        filepath = prog["file"]
        result = {
            "name":       name,
            "file":       filepath,
            "status":     "pass",
            "errors":     [],
            "violations": [],
            "error_msg":  None
        }

        try:
            # 1. Load and parse
            st_code = load_st_file(filepath)
            logic   = parse_st(st_code)

            # 2. Run through harness
            harness = TestHarness()
            harness.load_scenario(scenario)
            if properties:
                harness.properties = properties

            # Suppress per-tick output
            import io, sys
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            harness.run(max_time_ms=max_time_ms, step_ms=step_ms,
                        logic=logic, wiring=wiring)
            sys.stdout = old_stdout

            # 3. Assert expected outputs
            assertion = harness.assert_expected()
            result["errors"]     = assertion["errors"]
            result["violations"] = harness.violations
            result["status"]     = "pass" if assertion["passed"] else "fail"

        except Exception as e:
            result["status"]    = "error"
            result["error_msg"] = str(e)

        results.append(result)

    return results


def print_batch_results(results):
    """Print per-program results in a readable format."""
    print("=" * 60)
    print("  BATCH PROGRAM RUNNER RESULTS")
    print("=" * 60)

    for r in results:
        status = r["status"].upper()
        vcount = len(r["violations"])
        v_tag  = f"  [{vcount} violation(s)]" if vcount else ""
        print(f"  [{status}]  {r['name']}  ({r['file']}){v_tag}")

        if r["error_msg"]:
            print(f"           ERROR: {r['error_msg']}")
        for err in r["errors"]:
            print(f"           ASSERTION: {err}")
        for v in r["violations"]:
            print(f"           VIOLATION t={v['time']}ms: {v['property']}")

    total  = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    errors = sum(1 for r in results if r["status"] == "error")
    print("-" * 60)
    print(f"  Total: {total}  |  Pass: {passed}  |  Fail: {failed}  |  Error: {errors}")
    print("=" * 60)


if __name__ == "__main__":
    from properties import make_property

    print("=" * 60)
    print("Phase 5 - Step 2: Batch Program Runner")
    print("=" * 60)

    # --- Programs to run ---
    programs = [
        {"name": "Motor Start",      "file": "programs/motor_start.st"},
        {"name": "Shuttle Control",  "file": "programs/shuttle_control.st"},
    ]

    # --- Shared scenario ---
    # X0=True (run), X1=False (no fault), X2=False (no jam)
    # At t=400ms inject fault X1=True — motor_start should stop Y0
    scenario = {
        "name": "Baseline: run then fault",
        "initial_inputs": {"X0": True, "X1": False, "X2": False},
        "events": [
            {"time": 400, "inputs": {"X1": True}}
        ],
        "expected": [
            {"time": 200, "outputs": {"Y0": True}},   # running before fault
            {"time": 500, "outputs": {"Y0": False}},  # stopped after fault
        ]
    }

    # --- Safety property ---
    prop_safety = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X1") is True)
    )

    # --- Run batch ---
    results = run_batch(
        programs,
        scenario,
        max_time_ms=700,
        step_ms=100,
        properties=[prop_safety]
    )

    print_batch_results(results)

    # --- Print full JSON results ---
    print("\n--- Full JSON Results ---")
    print(json.dumps(results, indent=2))

    # --- Assertions ---
    print("\n--- Assertions ---")

    # motor_start.st: X0 AND NOT X1 — correctly stops when X1=True → PASS
    r1 = results[0]
    assert r1["name"]   == "Motor Start",  "wrong name"
    assert r1["status"] == "pass",         f"motor_start expected pass, got {r1['status']}"
    assert len(r1["violations"]) == 0,     "motor_start: expected 0 violations"
    print(f"  PASS — Motor Start: status=pass, 0 violations")

    # shuttle_control.st: uses X2 for jam, not X1 — Y0 stays True when X1 fires
    # so assertion at t=500 (Y0=False) will FAIL, and safety property will VIOLATE
    r2 = results[1]
    assert r2["name"]   == "Shuttle Control", "wrong name"
    assert r2["status"] == "fail",            f"shuttle_control expected fail, got {r2['status']}"
    print(f"  PASS — Shuttle Control: status=fail (uses X2 not X1, assertion fails)")
    print(f"         errors: {r2['errors']}")
    print(f"         violations: {len(r2['violations'])}")
