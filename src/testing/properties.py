"""
properties.py — Property-Based Validation Framework

A property is a named safety rule that must hold at every simulation state.

Property structure:
  {
    "name":  str,                          # human-readable label
    "check": callable(state) -> bool       # True = property holds, False = violation
  }

State structure passed to check():
  {
    "time":    int,   # current simulation time in ms
    "inputs":  dict,  # PLC input snapshot at this tick
    "outputs": dict   # PLC output snapshot at this tick
  }

Usage:
  prop = make_property("Y0 requires X0", lambda s: not (s["outputs"].get("Y0") and not s["inputs"].get("X0")))
  result = check_property(prop, state)
  # result: {"holds": bool, "property": name, "state": state}
"""


def make_property(name, check_fn):
    """
    Create a property dict.

    Args:
        name     : str       — human-readable property name
        check_fn : callable  — takes a state dict, returns True if property holds

    Returns:
        {"name": str, "check": callable}
    """
    if not callable(check_fn):
        raise TypeError(f"check_fn must be callable, got {type(check_fn)}")
    return {
        "name":  name,
        "check": check_fn
    }


def check_property(prop, state):
    """
    Evaluate a single property against a state snapshot.

    Args:
        prop  : property dict from make_property()
        state : {"time": int, "inputs": dict, "outputs": dict}

    Returns:
        {
          "holds":    bool,
          "property": str,   # property name
          "state":    dict   # the state that was checked
        }
    """
    holds = bool(prop["check"](state))
    return {
        "holds":    holds,
        "property": prop["name"],
        "state":    state
    }


def validate_properties(properties, state):
    """
    Evaluate a list of properties against a single state.

    Returns a list of result dicts (one per property).
    Only returns results where holds=False (violations).
    Returns empty list if all properties hold.
    """
    violations = []
    for prop in properties:
        result = check_property(prop, state)
        if not result["holds"]:
            violations.append(result)
    return violations


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("Phase 4 - Step 8: Property-Based Validation Framework")
    print("=" * 60)

    # -------------------------------------------------------
    # Property: "Y0 must not be True when X1 is True"
    # (safety interlock — if fault sensor X1 is active,
    #  motor output Y0 must be off)
    # -------------------------------------------------------
    prop_safety = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X1") is True)
    )

    # -------------------------------------------------------
    # Property: "Y0 requires X0 to be True"
    # (Y0 can only be on if start command X0 is active)
    # -------------------------------------------------------
    prop_enable = make_property(
        "Y0 requires X0 to be True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X0") is not True)
    )

    properties = [prop_safety, prop_enable]

    # -------------------------------------------------------
    # Test states
    # -------------------------------------------------------
    states = [
        # State 1: X0=T, X1=F, Y0=T  — both properties hold
        {"time": 100, "inputs": {"X0": True,  "X1": False}, "outputs": {"Y0": True}},
        # State 2: X0=T, X1=T, Y0=T  — prop_safety VIOLATED (Y0 on while X1 active)
        {"time": 200, "inputs": {"X0": True,  "X1": True},  "outputs": {"Y0": True}},
        # State 3: X0=F, X1=F, Y0=T  — prop_enable VIOLATED (Y0 on without X0)
        {"time": 300, "inputs": {"X0": False, "X1": False}, "outputs": {"Y0": True}},
        # State 4: X0=F, X1=T, Y0=F  — both properties hold (Y0 is off)
        {"time": 400, "inputs": {"X0": False, "X1": True},  "outputs": {"Y0": False}},
    ]

    print()
    for state in states:
        violations = validate_properties(properties, state)
        status = "OK" if not violations else "VIOLATION"
        print(f"  t={state['time']}ms | inputs={state['inputs']} | "
              f"outputs={state['outputs']} -> [{status}]")
        for v in violations:
            print(f"    VIOLATED: {v['property']}")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n  --- Assertions ---")

    # State 1: no violations
    v1 = validate_properties(properties, states[0])
    assert v1 == [], f"State 1 should have no violations, got {v1}"
    print("  PASS — State 1: no violations")

    # State 2: prop_safety violated
    v2 = validate_properties(properties, states[1])
    assert len(v2) == 1,                                    "State 2: expected 1 violation"
    assert v2[0]["property"] == prop_safety["name"],        "State 2: wrong property violated"
    assert v2[0]["holds"] is False,                         "State 2: holds must be False"
    print(f"  PASS — State 2: '{v2[0]['property']}' violated")

    # State 3: prop_enable violated
    v3 = validate_properties(properties, states[2])
    assert len(v3) == 1,                                    "State 3: expected 1 violation"
    assert v3[0]["property"] == prop_enable["name"],        "State 3: wrong property violated"
    print(f"  PASS — State 3: '{v3[0]['property']}' violated")

    # State 4: no violations
    v4 = validate_properties(properties, states[3])
    assert v4 == [], f"State 4 should have no violations, got {v4}"
    print("  PASS — State 4: no violations")

    # check_property returns correct structure
    r = check_property(prop_safety, states[0])
    assert "holds"    in r, "result must have 'holds'"
    assert "property" in r, "result must have 'property'"
    assert "state"    in r, "result must have 'state'"
    print("  PASS — check_property returns correct structure")
