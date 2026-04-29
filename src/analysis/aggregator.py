"""
aggregator.py — Failure Aggregation System

Aggregates results from batch scenario execution into a structured summary.
Collects failures, property violations, and prepares coverage gap data
for Step 7.
"""


def aggregate_results(results):
    """
    Aggregate a list of scenario result dicts into a summary.

    Args:
        results: list of result dicts from execute_scenarios()

    Returns:
        {
          "total_runs":        int,
          "passed":            int,
          "failed":            int,
          "errors":            int,
          "violations":        int,   # total violation events across all scenarios
          "failures": [
            {
              "scenario":   str,
              "errors":     [...],    # assertion failure messages
              "violations": [...]     # property violation dicts
            }
          ],
          "violation_summary": {
            "<property_name>": {
              "count":     int,       # total times this property was violated
              "scenarios": [str, ...] # scenario names where it fired
            }
          }
        }
    """
    total_runs  = len(results)
    passed      = sum(1 for r in results if r["status"] == "pass")
    failed      = sum(1 for r in results if r["status"] == "fail")
    errors      = sum(1 for r in results if r["status"] == "error")
    total_viols = sum(len(r.get("violations", [])) for r in results)

    failures = []
    violation_summary = {}

    for r in results:
        scenario_name = r["scenario"]
        r_errors      = r.get("errors", [])
        r_violations  = r.get("violations", [])

        # Collect failures (assertion errors OR violations)
        if r["status"] in ("fail", "error") or r_violations:
            failures.append({
                "scenario":   scenario_name,
                "status":     r["status"],
                "errors":     r_errors,
                "violations": r_violations,
                "error_msg":  r.get("error_msg")
            })

        # Aggregate violation counts per property
        for v in r_violations:
            prop = v["property"]
            if prop not in violation_summary:
                violation_summary[prop] = {"count": 0, "scenarios": []}
            violation_summary[prop]["count"] += 1
            if scenario_name not in violation_summary[prop]["scenarios"]:
                violation_summary[prop]["scenarios"].append(scenario_name)

    return {
        "total_runs":        total_runs,
        "passed":            passed,
        "failed":            failed,
        "errors":            errors,
        "violations":        total_viols,
        "failures":          failures,
        "violation_summary": violation_summary
    }


def print_aggregation_summary(summary):
    """Print the aggregated summary in a readable format."""
    print("=" * 60)
    print("  FAILURE AGGREGATION SUMMARY")
    print("=" * 60)
    print(f"  total_runs : {summary['total_runs']}")
    print(f"  passed     : {summary['passed']}")
    print(f"  failed     : {summary['failed']}")
    print(f"  errors     : {summary['errors']}")
    print(f"  violations : {summary['violations']}")

    if summary["failures"]:
        print()
        print("  --- Failures ---")
        for f in summary["failures"]:
            print(f"  [{f['status'].upper()}]  {f['scenario']}")
            for err in f["errors"]:
                print(f"    ASSERT: {err}")
            for v in f["violations"]:
                print(f"    VIOLATION t={v['time']}ms: {v['property']}")
            if f["error_msg"]:
                print(f"    ERROR: {f['error_msg']}")

    if summary["violation_summary"]:
        print()
        print("  --- Violation Summary (by property) ---")
        for prop, data in summary["violation_summary"].items():
            print(f"  Property : {prop}")
            print(f"    Total violations : {data['count']}")
            print(f"    Affected scenarios: {data['scenarios']}")

    print("=" * 60)


if __name__ == "__main__":
    import json
    from scenario_generator import generate_scenarios
    from batch_executor import execute_scenarios_from_file
    from properties import make_property

    print("=" * 60)
    print("Phase 5 - Step 6: Failure Aggregation System")
    print("=" * 60)

    # Safety property
    prop_safety = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X1") is True)
    )

    # -------------------------------------------------------
    # Run motor_start.st — 4 scenarios
    # -------------------------------------------------------
    gen_motor = generate_scenarios(
        inputs=["X0", "X1"],
        timing=[300],
        max_scenarios=8,
        base_name="Motor"
    )
    batch_motor = execute_scenarios_from_file(
        st_file="programs/motor_start.st",
        scenarios=gen_motor["scenarios"],
        max_time_ms=500,
        step_ms=100,
        properties=[prop_safety]
    )

    # -------------------------------------------------------
    # Run shuttle_control.st — 4 scenarios
    # -------------------------------------------------------
    gen_shuttle = generate_scenarios(
        inputs=["X0", "X1"],
        timing=[300],
        max_scenarios=8,
        base_name="Shuttle"
    )
    batch_shuttle = execute_scenarios_from_file(
        st_file="programs/shuttle_control.st",
        scenarios=gen_shuttle["scenarios"],
        max_time_ms=500,
        step_ms=100,
        properties=[prop_safety]
    )

    # -------------------------------------------------------
    # Aggregate both batches together
    # -------------------------------------------------------
    all_results = batch_motor["results"] + batch_shuttle["results"]
    summary = aggregate_results(all_results)

    print_aggregation_summary(summary)

    # --- Raw JSON ---
    print("\n--- Aggregation JSON ---")
    # Omit timelines from violations state for brevity
    print(json.dumps({
        "total_runs":        summary["total_runs"],
        "passed":            summary["passed"],
        "failed":            summary["failed"],
        "errors":            summary["errors"],
        "violations":        summary["violations"],
        "violation_summary": summary["violation_summary"]
    }, indent=2))

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert summary["total_runs"] == 8,   "8 total scenarios (4+4)"
    print(f"  PASS — total_runs=8")

    # motor_start: 1 pass (X0=T,X1=F), 3 fail (wrong assertion), 0 violations
    # shuttle_control: 4 pass (no expected), 3 violations on X0=T,X1=T scenario
    assert summary["violations"] == 3,   "3 total violations (shuttle X0=T,X1=T)"
    print(f"  PASS — violations=3")

    assert len(summary["violation_summary"]) == 1, "1 unique property violated"
    prop_name = "Y0 must not be True when X1 is True"
    assert prop_name in summary["violation_summary"]
    assert summary["violation_summary"][prop_name]["count"] == 3
    print(f"  PASS — violation_summary correct: '{prop_name}' count=3")

    # Failures list includes scenarios with assertion errors OR violations
    assert len(summary["failures"]) > 0, "failures list must not be empty"
    print(f"  PASS — failures list has {len(summary['failures'])} entries")
