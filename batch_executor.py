"""
batch_executor.py — Batch Scenario Execution

Runs a list of generated scenarios against a single ST program
and collects per-scenario results.
"""

import io
import sys
import json

from st_loader import load_st_file
from st_parser import parse_st
from test_harness import TestHarness


def execute_scenarios(scenarios, logic, max_time_ms=1000, step_ms=100,
                      wiring=None, properties=None):
    """
    Run a list of scenario dicts against pre-parsed logic.

    Args:
        scenarios   : list of scenario dicts (from expand_template or generate_scenarios)
        logic       : parsed logic list from parse_st()
        max_time_ms : simulation duration per scenario
        step_ms     : tick size in ms
        wiring      : optional wiring callback(plc, loom, t)
        properties  : optional list of property dicts

    Returns:
        list of result dicts:
        [
          {
            "scenario":   str,          # scenario name
            "status":     "pass"|"fail"|"error",
            "errors":     [...],        # assertion failures
            "violations": [...],        # property violations
            "timeline":   [...],        # full output timeline
            "error_msg":  str | None
          }
        ]
    """
    results = []

    for scenario in scenarios:
        result = {
            "scenario":  scenario["name"],
            "status":    "pass",
            "errors":    [],
            "violations": [],
            "timeline":  [],
            "error_msg": None
        }

        try:
            harness = TestHarness()
            harness.load_scenario(scenario)
            if properties:
                harness.properties = list(properties)

            # Suppress per-tick output
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()
            harness.run(max_time_ms=max_time_ms, step_ms=step_ms,
                        logic=logic, wiring=wiring)
            sys.stdout = old_stdout

            assertion = harness.assert_expected()
            result["errors"]     = assertion["errors"]
            result["violations"] = harness.violations
            result["timeline"]   = harness.output_timeline
            result["status"]     = "pass" if assertion["passed"] else "fail"

        except Exception as e:
            sys.stdout = sys.__stdout__   # safety restore
            result["status"]    = "error"
            result["error_msg"] = str(e)

        results.append(result)

    return results


def execute_scenarios_from_file(st_file, scenarios, max_time_ms=1000,
                                step_ms=100, wiring=None, properties=None):
    """
    Convenience wrapper: load ST file, parse, then execute all scenarios.

    Returns same structure as execute_scenarios() plus metadata:
        {
          "program":  str,       # st_file path
          "results":  [...]
        }
    """
    st_code = load_st_file(st_file)
    logic   = parse_st(st_code)
    results = execute_scenarios(scenarios, logic,
                                max_time_ms=max_time_ms,
                                step_ms=step_ms,
                                wiring=wiring,
                                properties=properties)
    return {"program": st_file, "results": results}


def print_execution_summary(batch_result):
    """Print a compact summary of batch execution results."""
    program = batch_result["program"]
    results = batch_result["results"]

    total      = len(results)
    passed     = sum(1 for r in results if r["status"] == "pass")
    failed     = sum(1 for r in results if r["status"] == "fail")
    errors     = sum(1 for r in results if r["status"] == "error")
    violations = sum(len(r["violations"]) for r in results)

    print(f"  Program : {program}")
    print(f"  Scenarios run : {total}")
    print(f"  Pass: {passed}  Fail: {failed}  Error: {errors}  "
          f"Total violations: {violations}")
    print()

    for r in results:
        status = r["status"].upper()
        vcount = len(r["violations"])
        v_tag  = f"  [{vcount}V]" if vcount else ""
        print(f"    [{status}]{v_tag}  {r['scenario']}")
        for err in r["errors"]:
            print(f"             ASSERT: {err}")
        for v in r["violations"]:
            print(f"             VIOLATION t={v['time']}ms: {v['property']}")


if __name__ == "__main__":
    from scenario_generator import generate_scenarios
    from properties import make_property

    print("=" * 60)
    print("Phase 5 - Step 5: Batch Scenario Execution")
    print("=" * 60)

    # -------------------------------------------------------
    # Program: motor_start.st
    # Inputs: X0 (run), X1 (fault)
    # Generate all 4 combinations, timing at 300ms
    # Expected: Y0=True only when X0=True AND X1=False
    # -------------------------------------------------------
    gen = generate_scenarios(
        inputs=["X0", "X1"],
        timing=[300],
        max_scenarios=8,
        base_name="MotorBatch",
        expected=[
            # We'll assert Y0 at t=400ms (after event fires at 300ms)
            {"time": 400, "outputs": {"Y0": True}}
        ]
    )

    print(f"\nGenerated {gen['generated']} scenarios "
          f"(total possible: {gen['total_possible']}, "
          f"capped: {gen['capped']})")

    # Safety property
    prop_safety = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X1") is True)
    )

    # Run batch
    batch = execute_scenarios_from_file(
        st_file="programs/motor_start.st",
        scenarios=gen["scenarios"],
        max_time_ms=500,
        step_ms=100,
        properties=[prop_safety]
    )

    print()
    print("=" * 60)
    print("  BATCH EXECUTION SUMMARY")
    print("=" * 60)
    print_execution_summary(batch)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("--- Assertions ---")
    results = batch["results"]

    # Scenario [1]: X0=F, X1=F → Y0=False at t=400 → FAIL (expected True)
    r1 = results[0]
    assert r1["status"] == "fail",  f"[1] X0=F,X1=F: Y0=False, expected True → fail"
    print(f"  PASS — [{r1['scenario']}]: fail (Y0=False, expected True)")

    # Scenario [2]: X0=F, X1=T → Y0=False → FAIL + violation
    r2 = results[1]
    assert r2["status"] == "fail",  f"[2] X0=F,X1=T: Y0=False → fail"
    print(f"  PASS — [{r2['scenario']}]: fail (Y0=False, expected True)")

    # Scenario [3]: X0=T, X1=F → Y0=True → PASS
    r3 = results[2]
    assert r3["status"] == "pass",  f"[3] X0=T,X1=F: Y0=True → pass"
    assert len(r3["violations"]) == 0
    print(f"  PASS — [{r3['scenario']}]: pass (Y0=True, no violations)")

    # Scenario [4]: X0=T, X1=T → Y0=False (ELSE branch) → FAIL assertion, no violation
    # (logic correctly gates Y0 off — property holds, assertion fails because expected True)
    r4 = results[3]
    assert r4["status"] == "fail",  f"[4] X0=T,X1=T: Y0=False → fail"
    assert len(r4["violations"]) == 0, "no violation — logic correctly stops Y0"
    print(f"  PASS — [{r4['scenario']}]: fail (assertion wrong) + 0 violations (logic correct)")

    # Timeline captured for each result
    for r in results:
        assert len(r["timeline"]) > 0, f"{r['scenario']}: timeline must not be empty"
    print("  PASS — All scenarios have non-empty timelines")

    # -------------------------------------------------------
    # Second batch: shuttle_control.st — property violation
    # expected when X1=True (shuttle uses X2 for jam, not X1)
    # -------------------------------------------------------
    print()
    print("--- Second batch: shuttle_control.st (violation check) ---")

    gen2 = generate_scenarios(
        inputs=["X0", "X1"],
        timing=[300],
        max_scenarios=4,
        base_name="ShuttleBatch"
    )

    batch2 = execute_scenarios_from_file(
        st_file="programs/shuttle_control.st",
        scenarios=gen2["scenarios"],
        max_time_ms=500,
        step_ms=100,
        properties=[prop_safety]
    )

    print_execution_summary(batch2)

    # Scenario where X0=T, X1=T: shuttle_control ignores X1 → Y0 stays True → VIOLATION
    r2_4 = batch2["results"][3]   # X0=T, X1=T
    assert len(r2_4["violations"]) > 0, "shuttle_control: expected violation when X1=True"
    print(f"  PASS — shuttle_control X0=T,X1=T: {len(r2_4['violations'])} violation(s) detected")
