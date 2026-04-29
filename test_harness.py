import json
from plc import PLC
from loom import LoomState
from clock import SimulationClock

class TestHarness:
    def __init__(self):
        self.plc = None
        self.loom = None
        self.clock = None
        self.scenario = None
        self.output_timeline = []

    def load_scenario(self, scenario):
        self.scenario = scenario
        self.output_timeline = []

    def run(self, max_time_ms=1000, step_ms=100, logic=None):
        print(f"--- Running Scenario: {self.scenario['name']} ---")
        
        self.plc = PLC()
        if logic:
            self.plc.logic = logic
            
        self.loom = LoomState()
        self.clock = SimulationClock()
        
        # Apply initial inputs
        initial_inputs = self.scenario.get("initial_inputs", {})
        for k, v in initial_inputs.items():
            self.plc.inputs[k] = v
            
        print(f"Initial inputs applied: {self.plc.inputs}")
        
        events = self.scenario.get("events", [])
        
        # Run simulation over time
        while self.clock.get_time() < max_time_ms:
            self.clock.advance(step_ms)
            current_time = self.clock.get_time()
            
            # 1. Process Event Injections (BEFORE Scan)
            for event in events:
                if event["time"] == current_time:
                    print(f"  [Event] At {current_time}ms: Injecting {event['inputs']}")
                    for k, v in event["inputs"].items():
                        self.plc.inputs[k] = v
            
            # 2. Scan PLC
            self.plc.scan(current_time)
            
            # 3. Capture Outputs — snapshot inputs too for full traceability
            self.output_timeline.append({
                "time": current_time,
                "inputs": dict(self.plc.inputs),
                "outputs": dict(self.plc.outputs)
            })
            
            # Simple fixed wiring for test harness
            if "Y0" in self.plc.outputs:
                self.loom.motor_running = self.plc.outputs["Y0"]
            
            # 4. Update Loom
            self.loom.update(current_time)
            
            print(f"Time: {current_time}ms | PLC Inputs: {self.plc.inputs} | PLC Outputs: {self.plc.outputs}")

    def print_output_timeline(self):
        """Print the captured output timeline in a human-readable table format."""
        if not self.output_timeline:
            print("  (no data captured)")
            return

        # Collect all unique output keys across all time steps
        all_output_keys = sorted(
            {key for entry in self.output_timeline for key in entry["outputs"]}
        )
        all_input_keys = sorted(
            {key for entry in self.output_timeline for key in entry["inputs"]}
        )

        # Build header
        col_time   = "Time(ms)"
        col_inputs = "  ".join(all_input_keys) if all_input_keys else "-"
        col_outputs = "  ".join(all_output_keys) if all_output_keys else "-"

        header = f"  {col_time:<10}  INPUTS: {col_inputs:<30}  OUTPUTS: {col_outputs}"
        separator = "  " + "-" * (len(header) - 2)

        print(header)
        print(separator)

        for entry in self.output_timeline:
            t = entry["time"]
            in_vals  = "  ".join(
                f"{k}={entry['inputs'].get(k, '-')}" for k in all_input_keys
            ) if all_input_keys else "-"
            out_vals = "  ".join(
                f"{k}={entry['outputs'].get(k, '-')}" for k in all_output_keys
            ) if all_output_keys else "-"
            print(f"  {t:<10}  {in_vals:<30}  {out_vals}")

    def get_output_at(self, time_ms):
        """Return the captured outputs dict at a specific time, or None if not found."""
        for entry in self.output_timeline:
            if entry["time"] == time_ms:
                return entry["outputs"]
        return None

    def assert_expected(self):
        """
        Compare scenario's expected outputs against the captured timeline.

        Returns a dict:
          {
            "passed": bool,
            "errors": ["At 500ms: expected Y0=True, got False", ...]
          }
        """
        errors = []
        expected_list = self.scenario.get("expected", [])

        for expectation in expected_list:
            t = expectation["time"]
            expected_outputs = expectation["outputs"]
            actual_outputs = self.get_output_at(t)

            if actual_outputs is None:
                errors.append(
                    f"At {t}ms: no data captured (simulation may not have reached this time)"
                )
                continue

            for key, expected_val in expected_outputs.items():
                actual_val = actual_outputs.get(key)
                if actual_val != expected_val:
                    errors.append(
                        f"At {t}ms: expected {key}={expected_val}, got {actual_val}"
                    )

        return {
            "passed": len(errors) == 0,
            "errors": errors
        }


def create_example_scenario():
    scenario = {
        "name": "Simple Motor Start",
        "initial_inputs": {
            "X0": False
        },
        "events": [
            {"time": 500, "inputs": {"X0": True}}
        ],
        "expected": [
            {"time": 600, "outputs": {"Y0": True}}
        ]
    }
    return scenario


if __name__ == "__main__":
    print("=" * 55)
    print("Phase 3 - Step 5: Assertion Engine Test")
    print("=" * 55)

    from st_parser import parse_st

    st_code = """
    IF X0 THEN
        Y0 := TRUE;
    END_IF;
    """
    logic = parse_st(st_code)

    # --------------------------------------------------
    # TEST CASE 1: PASSING — Y0 should be True at 600ms
    # --------------------------------------------------
    print("\n[Test Case 1] PASSING scenario")
    passing_scenario = {
        "name": "Motor Start - Passing",
        "initial_inputs": {"X0": False},
        "events": [
            {"time": 500, "inputs": {"X0": True}}
        ],
        "expected": [
            {"time": 400, "outputs": {"Y0": False}},   # before event: motor off
            {"time": 600, "outputs": {"Y0": True}}     # after event:  motor on
        ]
    }

    harness = TestHarness()
    harness.load_scenario(passing_scenario)
    harness.run(max_time_ms=700, step_ms=100, logic=logic)

    result = harness.assert_expected()
    print(f"\n  Result: {'PASS' if result['passed'] else 'FAIL'}")
    if result["errors"]:
        for err in result["errors"]:
            print(f"  ERROR: {err}")
    else:
        print("  All assertions passed.")

    # --------------------------------------------------
    # TEST CASE 2: FAILING — wrong expectation at 300ms
    # --------------------------------------------------
    print("\n[Test Case 2] FAILING scenario")
    failing_scenario = {
        "name": "Motor Start - Failing",
        "initial_inputs": {"X0": False},
        "events": [
            {"time": 500, "inputs": {"X0": True}}
        ],
        "expected": [
            # Wrong: Y0 should still be False at 300ms (X0 not yet set)
            {"time": 300, "outputs": {"Y0": True}},
            # Wrong: Y0 should be True at 600ms, not False
            {"time": 600, "outputs": {"Y0": False}},
            # Wrong: querying a time outside the simulation window
            {"time": 900, "outputs": {"Y0": True}}
        ]
    }

    harness2 = TestHarness()
    harness2.load_scenario(failing_scenario)
    harness2.run(max_time_ms=700, step_ms=100, logic=logic)

    result2 = harness2.assert_expected()
    print(f"\n  Result: {'PASS' if result2['passed'] else 'FAIL'}")
    if result2["errors"]:
        for err in result2["errors"]:
            print(f"  ERROR: {err}")
    else:
        print("  All assertions passed.")
