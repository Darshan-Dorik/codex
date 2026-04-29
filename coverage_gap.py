"""
coverage_gap.py — Coverage Gap Detection

Merges coverage data from multiple scenario runs and identifies:
  - Conditions that were never evaluated True
  - Conditions that were never evaluated False
  - Branches (THEN/ELSE) that were never executed
"""


def merge_coverage(results):
    """
    Merge per-scenario coverage reports into a single accumulated dict.

    Args:
        results: list of result dicts from execute_scenarios()
                 each must have a "coverage" key with get_coverage_report() output

    Returns:
        {
          "conditions": {
            "<label>": {"true": int, "false": int, "total": int}
          },
          "branches": {
            "<label>": {"then": int, "else": int, "total": int}
          }
        }
    """
    merged = {"conditions": {}, "branches": {}}

    for r in results:
        cov = r.get("coverage", {})

        for label, data in cov.get("conditions", {}).items():
            if label not in merged["conditions"]:
                merged["conditions"][label] = {"true": 0, "false": 0, "total": 0}
            merged["conditions"][label]["true"]  += data["true"]
            merged["conditions"][label]["false"] += data["false"]
            merged["conditions"][label]["total"] += data["total"]

        for label, data in cov.get("branches", {}).items():
            if label not in merged["branches"]:
                merged["branches"][label] = {"then": 0, "else": 0, "total": 0}
            merged["branches"][label]["then"]  += data["then"]
            merged["branches"][label]["else"]  += data["else"]
            merged["branches"][label]["total"] += data["total"]

    return merged


def detect_coverage_gaps(merged_coverage):
    """
    Identify coverage gaps from merged coverage data.

    Returns:
        {
          "conditions_never_true":  [str, ...],  # labels where true == 0
          "conditions_never_false": [str, ...],  # labels where false == 0
          "branches_never_then":    [str, ...],  # labels where then == 0
          "branches_never_else":    [str, ...],  # labels where else == 0
          "fully_covered":          [str, ...],  # labels with both branches > 0
          "has_gaps":               bool
        }
    """
    cond_never_true  = []
    cond_never_false = []
    branch_no_then   = []
    branch_no_else   = []
    fully_covered    = []

    for label, data in merged_coverage["conditions"].items():
        if data["true"] == 0:
            cond_never_true.append(label)
        if data["false"] == 0:
            cond_never_false.append(label)

    for label, data in merged_coverage["branches"].items():
        no_then = data["then"] == 0
        no_else = data["else"] == 0
        if no_then:
            branch_no_then.append(label)
        if no_else:
            branch_no_else.append(label)
        if not no_then and not no_else:
            fully_covered.append(label)

    has_gaps = bool(
        cond_never_true or cond_never_false or
        branch_no_then  or branch_no_else
    )

    return {
        "conditions_never_true":  cond_never_true,
        "conditions_never_false": cond_never_false,
        "branches_never_then":    branch_no_then,
        "branches_never_else":    branch_no_else,
        "fully_covered":          fully_covered,
        "has_gaps":               has_gaps
    }


def print_coverage_gap_report(gaps, merged_coverage):
    """Print a human-readable coverage gap report."""
    print("=" * 60)
    print("  COVERAGE GAP REPORT")
    print("=" * 60)

    # Condition totals
    print("\n  Condition Coverage (accumulated across all scenarios):")
    for label, data in merged_coverage["conditions"].items():
        t = data["true"]
        f = data["false"]
        total = data["total"]
        print(f"    {label}")
        print(f"      TRUE : {t:>4} / {total}   FALSE: {f:>4} / {total}")

    # Branch totals
    print("\n  Branch Coverage (accumulated across all scenarios):")
    for label, data in merged_coverage["branches"].items():
        th = data["then"]
        el = data["else"]
        total = data["total"]
        status = "FULL" if th > 0 and el > 0 else "PARTIAL"
        print(f"    {label}  [{status}]")
        print(f"      THEN: {th:>4} / {total}   ELSE: {el:>4} / {total}")

    # Gaps
    print("\n  Gaps detected:" if gaps["has_gaps"] else "\n  No gaps detected.")

    if gaps["conditions_never_true"]:
        print("    Conditions NEVER TRUE:")
        for lbl in gaps["conditions_never_true"]:
            print(f"      - {lbl}")

    if gaps["conditions_never_false"]:
        print("    Conditions NEVER FALSE:")
        for lbl in gaps["conditions_never_false"]:
            print(f"      - {lbl}")

    if gaps["branches_never_then"]:
        print("    Branches THEN never executed:")
        for lbl in gaps["branches_never_then"]:
            print(f"      - {lbl}")

    if gaps["branches_never_else"]:
        print("    Branches ELSE never executed:")
        for lbl in gaps["branches_never_else"]:
            print(f"      - {lbl}")

    if gaps["fully_covered"]:
        print("    Fully covered conditions:")
        for lbl in gaps["fully_covered"]:
            print(f"      ✓ {lbl}")

    print("=" * 60)


if __name__ == "__main__":
    import json
    from scenario_generator import generate_scenarios
    from batch_executor import execute_scenarios_from_file

    print("=" * 60)
    print("Phase 5 - Step 7: Coverage Gap Detection")
    print("=" * 60)

    # -------------------------------------------------------
    # Test A: Run motor_start.st with ALL 4 combinations
    # → both branches should be fully covered
    # -------------------------------------------------------
    print("\nTest A — motor_start.st, all 4 input combinations")
    gen_all = generate_scenarios(
        inputs=["X0", "X1"], timing=[300], max_scenarios=4, base_name="Full"
    )
    batch_all = execute_scenarios_from_file(
        st_file="programs/motor_start.st",
        scenarios=gen_all["scenarios"],
        max_time_ms=500, step_ms=100
    )
    merged_all = merge_coverage(batch_all["results"])
    gaps_all   = detect_coverage_gaps(merged_all)
    print_coverage_gap_report(gaps_all, merged_all)

    # -------------------------------------------------------
    # Test B: Run motor_start.st with ONLY X0=True, X1=False
    # from the start AND no events — condition always True
    # → ELSE branch never executed
    # -------------------------------------------------------
    print("\nTest B — motor_start.st, X0=True X1=False always (gap expected)")
    from scenario_template import expand_template
    partial_scenarios = expand_template({
        "name": "Partial",
        "inputs": ["X0", "X1"],
        "timing": [300],
        "variations": [
            {
                "__initial__": {"X0": True, "X1": False},
                "X0": True, "X1": False   # event keeps same values — condition stays True
            }
        ],
        "expected": []
    })
    batch_partial = execute_scenarios_from_file(
        st_file="programs/motor_start.st",
        scenarios=partial_scenarios,
        max_time_ms=500, step_ms=100
    )
    merged_partial = merge_coverage(batch_partial["results"])
    gaps_partial   = detect_coverage_gaps(merged_partial)
    print_coverage_gap_report(gaps_partial, merged_partial)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("--- Assertions ---")

    # Test A: full coverage — no gaps
    assert gaps_all["has_gaps"] is False,                   "Test A: expected no gaps"
    assert len(gaps_all["fully_covered"]) > 0,              "Test A: at least 1 fully covered"
    print("  PASS — Test A: all 4 combos → no coverage gaps")

    # Test B: partial coverage — ELSE never executed
    assert gaps_partial["has_gaps"] is True,                "Test B: expected gaps"
    assert len(gaps_partial["conditions_never_false"]) > 0, "Test B: condition never False"
    assert len(gaps_partial["branches_never_else"]) > 0,    "Test B: ELSE never executed"
    print("  PASS — Test B: single combo → ELSE branch gap detected")
    print(f"         conditions_never_false: {gaps_partial['conditions_never_false']}")
    print(f"         branches_never_else:    {gaps_partial['branches_never_else']}")
