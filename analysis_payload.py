"""
analysis_payload.py — Structured Analysis Payload

Combines failures, coverage gaps, violations, and summary
into a single structured dict ready for export or AI debugging.

Output schema:
{
  "program":       str,
  "summary": {
    "total_runs":  int,
    "passed":      int,
    "failed":      int,
    "errors":      int,
    "violations":  int,
    "has_gaps":    bool
  },
  "failures": [
    {
      "scenario":   str,
      "status":     str,
      "errors":     [...],
      "violations": [{"time": int, "property": str, "state": {...}}]
    }
  ],
  "coverage_gaps": {
    "conditions_never_true":  [...],
    "conditions_never_false": [...],
    "branches_never_then":    [...],
    "branches_never_else":    [...],
    "fully_covered":          [...]
  },
  "violations": [
    {
      "property":  str,
      "count":     int,
      "scenarios": [...]
    }
  ]
}
"""

from aggregator import aggregate_results
from coverage_gap import merge_coverage, detect_coverage_gaps


def build_analysis_payload(program, results):
    """
    Build a structured analysis payload from batch execution results.

    Args:
        program : str  — ST file path (for labelling)
        results : list — result dicts from execute_scenarios()

    Returns:
        structured analysis payload dict
    """
    # Aggregate failures and violations
    agg = aggregate_results(results)

    # Merge and analyse coverage
    merged_cov = merge_coverage(results)
    gaps       = detect_coverage_gaps(merged_cov)

    # Flatten violation_summary into a list for the payload
    violations_list = [
        {
            "property":  prop,
            "count":     data["count"],
            "scenarios": data["scenarios"]
        }
        for prop, data in agg["violation_summary"].items()
    ]

    # Strip timelines from failures to keep payload compact
    # (full timelines are available in results if needed)
    compact_failures = []
    for f in agg["failures"]:
        compact_failures.append({
            "scenario":   f["scenario"],
            "status":     f["status"],
            "errors":     f["errors"],
            "violations": [
                {"time": v["time"], "property": v["property"],
                 "state": v["state"]}
                for v in f["violations"]
            ],
            "error_msg":  f.get("error_msg")
        })

    payload = {
        "program": program,
        "summary": {
            "total_runs": agg["total_runs"],
            "passed":     agg["passed"],
            "failed":     agg["failed"],
            "errors":     agg["errors"],
            "violations": agg["violations"],
            "has_gaps":   gaps["has_gaps"]
        },
        "failures":      compact_failures,
        "coverage_gaps": {
            "conditions_never_true":  gaps["conditions_never_true"],
            "conditions_never_false": gaps["conditions_never_false"],
            "branches_never_then":    gaps["branches_never_then"],
            "branches_never_else":    gaps["branches_never_else"],
            "fully_covered":          gaps["fully_covered"]
        },
        "violations": violations_list
    }

    return payload


def print_analysis_payload(payload):
    """Print a human-readable summary of the analysis payload."""
    print("=" * 60)
    print("  STRUCTURED ANALYSIS PAYLOAD")
    print("=" * 60)
    print(f"  Program : {payload['program']}")

    s = payload["summary"]
    print(f"\n  Summary:")
    print(f"    total_runs : {s['total_runs']}")
    print(f"    passed     : {s['passed']}")
    print(f"    failed     : {s['failed']}")
    print(f"    errors     : {s['errors']}")
    print(f"    violations : {s['violations']}")
    print(f"    has_gaps   : {s['has_gaps']}")

    if payload["failures"]:
        print(f"\n  Failures ({len(payload['failures'])}):")
        for f in payload["failures"]:
            print(f"    [{f['status'].upper()}] {f['scenario']}")
            for err in f["errors"]:
                print(f"      ASSERT: {err}")
            for v in f["violations"]:
                print(f"      VIOLATION t={v['time']}ms: {v['property']}")
    else:
        print("\n  Failures: none")

    g = payload["coverage_gaps"]
    print(f"\n  Coverage Gaps:")
    if g["conditions_never_true"]:
        print(f"    Conditions never TRUE  : {g['conditions_never_true']}")
    if g["conditions_never_false"]:
        print(f"    Conditions never FALSE : {g['conditions_never_false']}")
    if g["branches_never_then"]:
        print(f"    THEN never executed    : {g['branches_never_then']}")
    if g["branches_never_else"]:
        print(f"    ELSE never executed    : {g['branches_never_else']}")
    if g["fully_covered"]:
        print(f"    Fully covered          : {g['fully_covered']}")
    if not payload["summary"]["has_gaps"]:
        print("    (none)")

    if payload["violations"]:
        print(f"\n  Property Violations:")
        for v in payload["violations"]:
            print(f"    {v['property']}")
            print(f"      count={v['count']}  scenarios={v['scenarios']}")
    else:
        print("\n  Property Violations: none")

    print("=" * 60)


if __name__ == "__main__":
    import json
    from scenario_generator import generate_scenarios
    from batch_executor import execute_scenarios_from_file
    from properties import make_property

    print("=" * 60)
    print("Phase 5 - Step 8: Structured Analysis Payload")
    print("=" * 60)

    prop_safety = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X1") is True)
    )

    # -------------------------------------------------------
    # Payload A: motor_start.st — full coverage, no violations
    # -------------------------------------------------------
    print("\n--- Payload A: motor_start.st ---")
    gen_a = generate_scenarios(
        inputs=["X0", "X1"], timing=[300], max_scenarios=4, base_name="Motor"
    )
    batch_a = execute_scenarios_from_file(
        st_file="programs/motor_start.st",
        scenarios=gen_a["scenarios"],
        max_time_ms=500, step_ms=100,
        properties=[prop_safety]
    )
    payload_a = build_analysis_payload("programs/motor_start.st", batch_a["results"])
    print_analysis_payload(payload_a)

    # -------------------------------------------------------
    # Payload B: shuttle_control.st — violations + gap
    # Only run X0=True, X1=False (ELSE never hit for cond 1)
    # -------------------------------------------------------
    print("\n--- Payload B: shuttle_control.st (violations + gap) ---")
    from scenario_template import expand_template
    partial = expand_template({
        "name": "ShuttlePartial",
        "inputs": ["X0", "X1", "X2"],
        "timing": [300],
        "variations": [
            {"__initial__": {"X0": True}, "X0": True, "X1": True, "X2": False}
        ],
        "expected": []
    })
    batch_b = execute_scenarios_from_file(
        st_file="programs/shuttle_control.st",
        scenarios=partial,
        max_time_ms=500, step_ms=100,
        properties=[prop_safety]
    )
    payload_b = build_analysis_payload("programs/shuttle_control.st", batch_b["results"])
    print_analysis_payload(payload_b)

    # -------------------------------------------------------
    # Print full JSON for payload B
    # -------------------------------------------------------
    print("\n--- Payload B JSON ---")
    print(json.dumps(payload_b, indent=2))

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Payload A: no violations, no gaps
    assert payload_a["summary"]["violations"] == 0,    "A: no violations"
    assert payload_a["summary"]["has_gaps"]   is False, "A: no gaps"
    assert len(payload_a["violations"])       == 0,    "A: violations list empty"
    print("  PASS — Payload A: no violations, no gaps")

    # Payload B: violations present
    assert payload_b["summary"]["violations"] > 0,     "B: violations expected"
    assert len(payload_b["violations"])       > 0,     "B: violations list populated"
    print(f"  PASS — Payload B: {payload_b['summary']['violations']} violations")

    # Payload B: coverage gap (ELSE never hit for shuttle motor condition)
    assert payload_b["summary"]["has_gaps"] is True,   "B: gaps expected"
    print(f"  PASS — Payload B: coverage gaps detected")

    # Payload structure keys
    for key in ("program", "summary", "failures", "coverage_gaps", "violations"):
        assert key in payload_a, f"missing key: {key}"
    print("  PASS — Payload structure has all required keys")
