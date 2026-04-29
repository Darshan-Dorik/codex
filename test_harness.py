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


class ScenarioRunner:
    """
    Runs multiple scenarios sequentially and collects a summary report.

    Each entry in `scenarios` is a dict:
      {
        "scenario": <scenario dict>,
        "logic":    <parsed logic list>,
        "max_time_ms": int,   # optional, default 1000
        "step_ms":     int    # optional, default 100
      }
    """

    def __init__(self, verbose=True):
        self.verbose = verbose   # if False, suppresses per-tick output
        self.results = []        # list of result dicts after run_all()

    def run_all(self, entries):
        """Run every entry and populate self.results."""
        self.results = []

        for entry in entries:
            scenario   = entry["scenario"]
            logic      = entry.get("logic", [])
            max_time   = entry.get("max_time_ms", 1000)
            step       = entry.get("step_ms", 100)

            harness = TestHarness()
            harness.load_scenario(scenario)

            if not self.verbose:
                # Suppress per-tick print by temporarily redirecting stdout
                import io, sys
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()

            harness.run(max_time_ms=max_time, step_ms=step, logic=logic)

            if not self.verbose:
                sys.stdout = old_stdout

            assertion = harness.assert_expected()

            self.results.append({
                "name":   scenario["name"],
                "passed": assertion["passed"],
                "errors": assertion["errors"]
            })

        return self.results

    def print_summary(self):
        """Print a human-readable summary of all scenario results."""
        total  = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        print("=" * 55)
        print("  SCENARIO RUNNER SUMMARY")
        print("=" * 55)

        for r in self.results:
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  [{status}]  {r['name']}")
            for err in r["errors"]:
                print(f"           ERROR: {err}")

        print("-" * 55)
        print(f"  Total: {total}  |  Passed: {passed}  |  Failed: {failed}")
        print("=" * 55)


if __name__ == "__main__":
    print("=" * 55)
    print("Phase 3 - Step 6: Multi-Scenario Runner Test")
    print("=" * 55)

    from st_parser import parse_st

    # --- Shared logic ---
    st_code = """
    IF X0 THEN
        Y0 := TRUE;
    END_IF;
    """
    logic = parse_st(st_code)

    # --------------------------------------------------
    # Scenario 1: PASS — motor off before event, on after
    # --------------------------------------------------
    scenario_1 = {
        "name": "Motor Off Then On (PASS)",
        "initial_inputs": {"X0": False},
        "events": [{"time": 300, "inputs": {"X0": True}}],
        "expected": [
            {"time": 200, "outputs": {"Y0": False}},
            {"time": 400, "outputs": {"Y0": True}},
            {"time": 500, "outputs": {"Y0": True}}
        ]
    }

    # --------------------------------------------------
    # Scenario 2: PASS — motor stays off (no start event)
    # --------------------------------------------------
    scenario_2 = {
        "name": "Motor Never Starts (PASS)",
        "initial_inputs": {"X0": False},
        "events": [],
        "expected": [
            {"time": 200, "outputs": {"Y0": False}},
            {"time": 500, "outputs": {"Y0": False}}
        ]
    }

    # --------------------------------------------------
    # Scenario 3: FAIL — wrong expectation on purpose
    # --------------------------------------------------
    scenario_3 = {
        "name": "Wrong Expectation (FAIL)",
        "initial_inputs": {"X0": False},
        "events": [{"time": 300, "inputs": {"X0": True}}],
        "expected": [
            # Motor should be False at 200ms, not True
            {"time": 200, "outputs": {"Y0": True}},
            # Motor should be True at 400ms, not False
            {"time": 400, "outputs": {"Y0": False}}
        ]
    }

    entries = [
        {"scenario": scenario_1, "logic": logic, "max_time_ms": 600, "step_ms": 100},
        {"scenario": scenario_2, "logic": logic, "max_time_ms": 600, "step_ms": 100},
        {"scenario": scenario_3, "logic": logic, "max_time_ms": 600, "step_ms": 100},
    ]

    runner = ScenarioRunner(verbose=False)  # suppress per-tick noise
    runner.run_all(entries)
    runner.print_summary()
