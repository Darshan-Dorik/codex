"""
scenario_generator.py — Controlled Scenario Generator

Generates scenarios automatically from a set of inputs and timing points.
Produces all boolean combinations of inputs but caps output at max_scenarios
to prevent combinatorial explosion.

Generation is deterministic: combinations are always produced in the same
order (sorted by input name, then by binary count order).
"""

from scenario_template import expand_template


def _all_combinations(inputs):
    """
    Generate all boolean combinations for a list of input names.
    Order: sorted input names, combinations in binary count order (0=False, 1=True).

    Example: inputs=["X0","X1"] ->
      [{"X0":False,"X1":False}, {"X0":False,"X1":True},
       {"X0":True, "X1":False}, {"X0":True, "X1":True}]
    """
    sorted_inputs = sorted(inputs)
    n = len(sorted_inputs)
    combos = []
    for i in range(2 ** n):
        combo = {}
        for bit, name in enumerate(reversed(sorted_inputs)):
            combo[name] = bool((i >> bit) & 1)
        combos.append(combo)
    return combos


def generate_scenarios(inputs, timing, max_scenarios=16,
                       base_name="Generated", expected=None):
    """
    Generate up to max_scenarios scenarios covering boolean input combinations.

    Args:
        inputs        : list of str — input variable names
        timing        : list of int — event injection times in ms
        max_scenarios : int — hard cap on number of scenarios (default 16)
        base_name     : str — prefix for scenario names
        expected      : list — optional shared expected assertions

    Returns:
        dict:
        {
          "scenarios":   [<scenario dict>, ...],
          "total_possible": int,   # 2^n before capping
          "generated":   int,      # actual count after cap
          "capped":      bool      # True if cap was applied
        }
    """
    if not inputs:
        raise ValueError("inputs list must not be empty")
    if not timing:
        raise ValueError("timing list must not be empty")
    if max_scenarios < 1:
        raise ValueError("max_scenarios must be >= 1")

    all_combos    = _all_combinations(inputs)
    total_possible = len(all_combos)
    capped        = total_possible > max_scenarios
    selected      = all_combos[:max_scenarios]

    template = {
        "name":       base_name,
        "inputs":     inputs,
        "timing":     timing,
        "variations": selected,
        "expected":   expected or []
    }

    scenarios = expand_template(template)

    return {
        "scenarios":       scenarios,
        "total_possible":  total_possible,
        "generated":       len(scenarios),
        "capped":          capped
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 5 - Step 4: Controlled Scenario Generator")
    print("=" * 60)

    # -------------------------------------------------------
    # Test 1: 2 inputs — 4 combinations, no cap needed
    # -------------------------------------------------------
    print("\nTest 1 — 2 inputs (X0, X1), max=16, timing=[200, 500]")
    result1 = generate_scenarios(
        inputs=["X0", "X1"],
        timing=[200, 500],
        max_scenarios=16,
        base_name="Motor2"
    )
    print(f"  total_possible : {result1['total_possible']}")
    print(f"  generated      : {result1['generated']}")
    print(f"  capped         : {result1['capped']}")
    print(f"  scenarios:")
    for s in result1["scenarios"]:
        ev = s["events"][0]["inputs"]
        print(f"    {s['name']:25}  initial={s['initial_inputs']}  event={ev}")

    # -------------------------------------------------------
    # Test 2: 3 inputs — 8 combinations, no cap needed
    # -------------------------------------------------------
    print("\nTest 2 — 3 inputs (X0, X1, X2), max=16, timing=[300]")
    result2 = generate_scenarios(
        inputs=["X0", "X1", "X2"],
        timing=[300],
        max_scenarios=16,
        base_name="Shuttle3"
    )
    print(f"  total_possible : {result2['total_possible']}")
    print(f"  generated      : {result2['generated']}")
    print(f"  capped         : {result2['capped']}")

    # -------------------------------------------------------
    # Test 3: 4 inputs — 16 combinations, cap at 6
    # -------------------------------------------------------
    print("\nTest 3 — 4 inputs (X0-X3), max=6 (cap applied), timing=[400]")
    result3 = generate_scenarios(
        inputs=["X0", "X1", "X2", "X3"],
        timing=[400],
        max_scenarios=6,
        base_name="Capped4"
    )
    print(f"  total_possible : {result3['total_possible']}")
    print(f"  generated      : {result3['generated']}")
    print(f"  capped         : {result3['capped']}")
    print(f"  scenarios generated:")
    for s in result3["scenarios"]:
        print(f"    {s['name']:20}  event={s['events'][0]['inputs']}")

    # -------------------------------------------------------
    # Test 4: 5 inputs — 32 combinations, cap at 10
    # -------------------------------------------------------
    print("\nTest 4 — 5 inputs, max=10 (verify no explosion)")
    result4 = generate_scenarios(
        inputs=["X0", "X1", "X2", "X3", "X4"],
        timing=[100],
        max_scenarios=10,
        base_name="Big5"
    )
    print(f"  total_possible : {result4['total_possible']}")
    print(f"  generated      : {result4['generated']}")
    print(f"  capped         : {result4['capped']}")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Test 1: 2 inputs → 4 combos, no cap
    assert result1["total_possible"] == 4,   "2 inputs → 4 combos"
    assert result1["generated"]      == 4,   "all 4 generated"
    assert result1["capped"]         is False
    print("  PASS — Test 1: 2 inputs, 4 scenarios, no cap")

    # Test 2: 3 inputs → 8 combos, no cap
    assert result2["total_possible"] == 8,   "3 inputs → 8 combos"
    assert result2["generated"]      == 8
    assert result2["capped"]         is False
    print("  PASS — Test 2: 3 inputs, 8 scenarios, no cap")

    # Test 3: 4 inputs → 16 combos, capped at 6
    assert result3["total_possible"] == 16,  "4 inputs → 16 combos"
    assert result3["generated"]      == 6,   "capped at 6"
    assert result3["capped"]         is True
    print("  PASS — Test 3: 4 inputs, capped at 6/16")

    # Test 4: 5 inputs → 32 combos, capped at 10
    assert result4["total_possible"] == 32,  "5 inputs → 32 combos"
    assert result4["generated"]      == 10,  "capped at 10"
    assert result4["capped"]         is True
    print("  PASS — Test 4: 5 inputs, capped at 10/32 — no explosion")

    # Determinism: running twice gives identical scenario names and events
    r_a = generate_scenarios(["X0", "X1"], [100], max_scenarios=4, base_name="Det")
    r_b = generate_scenarios(["X0", "X1"], [100], max_scenarios=4, base_name="Det")
    assert r_a["scenarios"] == r_b["scenarios"], "generation must be deterministic"
    print("  PASS — Determinism: two runs produce identical scenarios")
