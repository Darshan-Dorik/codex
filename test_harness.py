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
    print("Phase 3 - Step 4: Output Capture System Test")
    print("=" * 55)

    from st_parser import parse_st

    st_code = """
    IF X0 THEN
        Y0 := TRUE;
    END_IF;
    """

    scenario = create_example_scenario()
    harness = TestHarness()
    harness.load_scenario(scenario)

    print()
    harness.run(max_time_ms=700, step_ms=100, logic=parse_st(st_code))

    # --- Human-readable timeline table ---
    print()
    print("--- Captured Output Timeline (Table) ---")
    harness.print_output_timeline()

    # --- Raw JSON for verification ---
    print()
    print("--- Captured Output Timeline (JSON) ---")
    print(json.dumps(harness.output_timeline, indent=2))

    # --- Spot-check: query a specific time ---
    print()
    print("--- Spot-check: get_output_at(600ms) ---")
    result = harness.get_output_at(600)
    print(f"  Outputs at 600ms: {result}")
    expected_y0 = True
    actual_y0   = result.get("Y0") if result else None
    status = "PASS" if actual_y0 == expected_y0 else "FAIL"
    print(f"  Y0 expected={expected_y0}, got={actual_y0} -> [{status}]")
