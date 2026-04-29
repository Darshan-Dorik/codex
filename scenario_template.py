"""
scenario_template.py — Scenario Template System

A template defines the structure of a family of scenarios.
Expanding a template produces a list of concrete scenario dicts
compatible with TestHarness.load_scenario().

Template format:
{
  "name":       str,                  # base name (index appended per scenario)
  "inputs":     [str, ...],           # input variable names
  "timing":     [int, ...],           # event injection times in ms (ascending)
  "variations": [                     # one scenario per variation
    {"X0": true, "X1": false},        # input values at each timing point
    {"X0": false, "X1": true},
    ...
  ],
  "expected":   [                     # optional shared assertions
    {"time": int, "outputs": {...}}
  ]
}

Each variation is applied as a single event at every timing point.
initial_inputs are all False by default (can be overridden per variation
using the special key "__initial__").
"""


def expand_template(template):
    """
    Expand a scenario template into a list of concrete scenario dicts.

    Each variation produces one scenario:
      - initial_inputs: all inputs False, unless variation has "__initial__"
      - events: one event per timing point, all using the variation's values
      - expected: copied from template (shared across all scenarios)

    Args:
        template: dict — see module docstring for format

    Returns:
        list of scenario dicts
    """
    base_name  = template["name"]
    inputs     = template["inputs"]
    timing     = template["timing"]
    variations = template["variations"]
    expected   = template.get("expected", [])

    scenarios = []

    for idx, variation in enumerate(variations, start=1):
        # Separate __initial__ override from event values
        initial_override = variation.get("__initial__", {})
        event_values     = {k: v for k, v in variation.items()
                            if k != "__initial__"}

        # Build initial_inputs: all False, then apply override
        initial_inputs = {inp: False for inp in inputs}
        initial_inputs.update(initial_override)

        # Build events: one per timing point, all with the same variation values
        events = []
        for t in timing:
            events.append({
                "time":   t,
                "inputs": dict(event_values)
            })

        scenario = {
            "name":           f"{base_name} [{idx}]",
            "initial_inputs": initial_inputs,
            "events":         events,
            "expected":       list(expected)
        }
        scenarios.append(scenario)

    return scenarios


def print_expanded_scenarios(scenarios):
    """Print expanded scenarios in a readable format."""
    print(f"  Expanded {len(scenarios)} scenario(s):")
    print()
    for s in scenarios:
        print(f"  Scenario : {s['name']}")
        print(f"    initial_inputs : {s['initial_inputs']}")
        for ev in s["events"]:
            print(f"    event t={ev['time']}ms : {ev['inputs']}")
        if s["expected"]:
            for ex in s["expected"]:
                print(f"    expected t={ex['time']}ms : {ex['outputs']}")
        print()


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("Phase 5 - Step 3: Scenario Template System")
    print("=" * 60)

    # -------------------------------------------------------
    # Template 1: motor_start — 2 inputs, 2 timing points,
    # 4 variations covering all combinations of X0/X1
    # -------------------------------------------------------
    template_motor = {
        "name":   "Motor Start",
        "inputs": ["X0", "X1"],
        "timing": [200, 500],
        "variations": [
            {"X0": True,  "X1": False},   # run, no fault
            {"X0": True,  "X1": True},    # run + fault
            {"X0": False, "X1": False},   # no run, no fault
            {"X0": False, "X1": True},    # no run + fault
        ],
        "expected": []
    }

    print("\nTemplate 1 — Motor Start (4 variations, 2 timing points):")
    print(json.dumps({k: v for k, v in template_motor.items()
                      if k != "variations"}, indent=2))
    print(f"  variations: {len(template_motor['variations'])}")

    scenarios_motor = expand_template(template_motor)
    print()
    print_expanded_scenarios(scenarios_motor)

    # -------------------------------------------------------
    # Template 2: shuttle_control — 3 inputs, 1 timing point,
    # 3 variations, with __initial__ override on one
    # -------------------------------------------------------
    template_shuttle = {
        "name":   "Shuttle Control",
        "inputs": ["X0", "X1", "X2"],
        "timing": [300],
        "variations": [
            {"X0": True,  "X1": False, "X2": False},   # normal run
            {"X0": True,  "X1": True,  "X2": False},   # position reached
            {
                "__initial__": {"X0": True},            # motor on from start
                "X0": True, "X1": False, "X2": True    # jam at t=300
            },
        ],
        "expected": []
    }

    print("\nTemplate 2 — Shuttle Control (3 variations, 1 timing point):")
    scenarios_shuttle = expand_template(template_shuttle)
    print_expanded_scenarios(scenarios_shuttle)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("--- Assertions ---")

    # Template 1: 4 variations → 4 scenarios
    assert len(scenarios_motor) == 4,                   "expected 4 scenarios"
    # Each scenario has 2 events (one per timing point)
    assert len(scenarios_motor[0]["events"]) == 2,      "expected 2 events"
    assert scenarios_motor[0]["events"][0]["time"] == 200
    assert scenarios_motor[0]["events"][1]["time"] == 500
    # initial_inputs all False by default
    assert scenarios_motor[0]["initial_inputs"] == {"X0": False, "X1": False}
    # Variation values in events
    assert scenarios_motor[0]["events"][0]["inputs"] == {"X0": True, "X1": False}
    print("  PASS — Template 1: 4 scenarios, 2 events each, correct structure")

    # Template 2: 3 variations → 3 scenarios
    assert len(scenarios_shuttle) == 3,                 "expected 3 scenarios"
    # Variation 3 has __initial__ override
    s3 = scenarios_shuttle[2]
    assert s3["initial_inputs"]["X0"] is True,          "__initial__ override applied"
    assert s3["events"][0]["inputs"]["X2"] is True,     "jam event correct"
    print("  PASS — Template 2: 3 scenarios, __initial__ override works")

    # Scenario names include index
    assert scenarios_motor[0]["name"] == "Motor Start [1]"
    assert scenarios_motor[3]["name"] == "Motor Start [4]"
    print("  PASS — Scenario names include index")
