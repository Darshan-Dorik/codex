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

    def run(self, max_time_ms=1000, step_ms=100, logic=None, wiring=None):
        """
        Run the scenario simulation.

        wiring: optional callable(plc, loom, current_time_ms) invoked after
                each scan cycle.  Use it to wire loom sensor state back into
                PLC inputs (e.g. shuttle position sensor, jam sensor).
                If None, only the default Y0 -> motor_running link is applied.
        """
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
            
            # 3. Default wiring: PLC Y0 -> loom motor
            if "Y0" in self.plc.outputs:
                self.loom.motor_running = self.plc.outputs["Y0"]

            # 4. Custom wiring callback (loom sensors -> PLC inputs)
            if wiring:
                wiring(self.plc, self.loom, current_time)

            # 5. Capture Outputs — snapshot inputs too for full traceability
            self.output_timeline.append({
                "time": current_time,
                "inputs": dict(self.plc.inputs),
                "outputs": dict(self.plc.outputs)
            })
            
            # 6. Update Loom physics
            self.loom.update(current_time)
            
            print(f"Time: {current_time}ms | Inputs: {self.plc.inputs} | Outputs: {self.plc.outputs} | ShuttlePos: {round(self.loom.shuttle_position, 2)}")

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
            "errors": ["At 500ms: expected Y0=True, got False", ...],
            "snapshots": [ <failure snapshot per failing assertion> ]
          }
        """
        errors    = []
        snapshots = []
        expected_list = self.scenario.get("expected", [])

        for expectation in expected_list:
            t = expectation["time"]
            expected_outputs = expectation["outputs"]
            actual_outputs = self.get_output_at(t)

            if actual_outputs is None:
                errors.append(
                    f"At {t}ms: no data captured (simulation may not have reached this time)"
                )
                snapshots.append(self._build_snapshot(t, {}, {}, "no data captured"))
                continue

            # Retrieve the full timeline entry for this time (includes inputs)
            timeline_entry = next(
                (e for e in self.output_timeline if e["time"] == t), {}
            )
            actual_inputs = timeline_entry.get("inputs", {})

            for key, expected_val in expected_outputs.items():
                actual_val = actual_outputs.get(key)
                if actual_val != expected_val:
                    msg = f"At {t}ms: expected {key}={expected_val}, got {actual_val}"
                    errors.append(msg)
                    snapshots.append(
                        self._build_snapshot(t, actual_inputs, actual_outputs, msg)
                    )

        return {
            "passed":    len(errors) == 0,
            "errors":    errors,
            "snapshots": snapshots
        }

    def _build_snapshot(self, time_ms, inputs, outputs, reason):
        """
        Build a failure snapshot dict capturing full machine state at time_ms.
        Loom state is read from self.loom (end-of-run state) when time matches
        the last tick; for mid-run failures we record what the timeline captured.
        """
        # Loom state at end of simulation (best available without per-tick loom history)
        loom_state = {}
        if self.loom is not None:
            loom_state = {
                "motor_running":    self.loom.motor_running,
                "shuttle_position": round(self.loom.shuttle_position, 4),
                "jam_detected":     self.loom.jam_detected
            }

        return {
            "timestamp_ms": time_ms,
            "reason":       reason,
            "inputs":       dict(inputs),
            "outputs":      dict(outputs),
            "loom_state":   loom_state
        }

    def print_failure_snapshots(self, snapshots):
        """Pretty-print a list of failure snapshots."""
        if not snapshots:
            print("  (no failure snapshots)")
            return
        for i, snap in enumerate(snapshots, 1):
            print(f"  --- Snapshot #{i} ---")
            print(f"  Timestamp : {snap['timestamp_ms']}ms")
            print(f"  Reason    : {snap['reason']}")
            print(f"  Inputs    : {snap['inputs']}")
            print(f"  Outputs   : {snap['outputs']}")
            print(f"  Loom State: {snap['loom_state']}")

    def replay_verify(self, runs=2, max_time_ms=1000, step_ms=100,
                      logic=None, wiring=None):
        """
        Run the loaded scenario `runs` times and verify every timeline is
        identical to the first run.

        Returns a dict:
          {
            "deterministic": bool,
            "timelines": [ <timeline from each run> ],
            "diffs": [ "Run 2 differs at tick index 3: ..." ]
          }
        """
        timelines = []

        for run_num in range(1, runs + 1):
            # Reset timeline before each run
            self.output_timeline = []
            self.run(
                max_time_ms=max_time_ms,
                step_ms=step_ms,
                logic=logic,
                wiring=wiring
            )
            timelines.append(list(self.output_timeline))  # deep copy of list

        # Compare every subsequent run against run 1
        reference = timelines[0]
        diffs = []

        for run_idx, timeline in enumerate(timelines[1:], start=2):
            if len(timeline) != len(reference):
                diffs.append(
                    f"Run {run_idx}: tick count differs "
                    f"(expected {len(reference)}, got {len(timeline)})"
                )
                continue
            for i, (ref_entry, actual_entry) in enumerate(
                zip(reference, timeline)
            ):
                if ref_entry != actual_entry:
                    diffs.append(
                        f"Run {run_idx} differs at tick index {i} "
                        f"(t={ref_entry['time']}ms): "
                        f"expected {ref_entry}, got {actual_entry}"
                    )

        return {
            "deterministic": len(diffs) == 0,
            "timelines":     timelines,
            "diffs":         diffs
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
            wiring     = entry.get("wiring", None)

            harness = TestHarness()
            harness.load_scenario(scenario)

            if not self.verbose:
                import io, sys
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()

            harness.run(max_time_ms=max_time, step_ms=step, logic=logic, wiring=wiring)

            if not self.verbose:
                sys.stdout = old_stdout

            assertion = harness.assert_expected()

            self.results.append({
                "name":      scenario["name"],
                "passed":    assertion["passed"],
                "errors":    assertion["errors"],
                "snapshots": assertion["snapshots"]
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
    print("=" * 60)
    print("Phase 3 - Step 9: Deterministic Replay")
    print("=" * 60)

    from st_parser import parse_st

    # -------------------------------------------------------
    # Scenario: jam detection with TON delay — exercises
    # timers, wiring callbacks, and event injection together.
    # A non-deterministic system would diverge on re-runs.
    # -------------------------------------------------------
    logic = [
        {"type": "ton", "id": "T0", "if": "X0", "pt": 0.3, "set": "Y0"},
        {"type": "interlock", "run": "Y0", "stop": "X2", "set": "Y1"}
    ]

    def wiring_replay(plc, loom, t):
        if t >= 500:
            loom.jam_detected = True
        plc.inputs["X2"] = loom.jam_detected

    scenario = {
        "name": "Deterministic Replay Test",
        "initial_inputs": {"X0": True, "X2": False},
        "events": [
            {"time": 200, "inputs": {"X0": False}},   # stop timer briefly
            {"time": 400, "inputs": {"X0": True}}     # restart timer
        ],
        "expected": []   # no assertions needed — replay itself is the test
    }

    harness = TestHarness()
    harness.load_scenario(scenario)

    import io, sys

    # Suppress per-tick output during replay (keep output clean)
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()

    result = harness.replay_verify(
        runs=3,
        max_time_ms=900,
        step_ms=100,
        logic=logic,
        wiring=wiring_replay
    )

    sys.stdout = old_stdout

    # --- Report ---
    status = "DETERMINISTIC" if result["deterministic"] else "NON-DETERMINISTIC"
    print(f"\n  Replay result: [{status}]")
    print(f"  Runs executed: {len(result['timelines'])}")
    print(f"  Ticks per run: {len(result['timelines'][0])}")

    if result["diffs"]:
        print("\n  DIFFERENCES FOUND:")
        for d in result["diffs"]:
            print(f"    {d}")
    else:
        print("  All runs produced identical output timelines.")

    # --- Side-by-side spot check: show tick 5 from each run ---
    print("\n  Spot-check: tick index 5 across all runs")
    for i, tl in enumerate(result["timelines"], 1):
        entry = tl[5]
        print(f"    Run {i} | t={entry['time']}ms | "
              f"inputs={entry['inputs']} | outputs={entry['outputs']}")

    # --- Verify assertion engine still works on replayed timeline ---
    print("\n  Assertion check on final replay timeline:")
    harness.output_timeline = result["timelines"][-1]
    harness.scenario["expected"] = [
        {"time": 400, "outputs": {"Y0": False}},  # timer reset, not yet fired
        {"time": 800, "outputs": {"Y1": False}}   # jam active, Y1 interlocked off
    ]
    assertion = harness.assert_expected()
    print(f"  Result: {'PASS' if assertion['passed'] else 'FAIL'}")
    for err in assertion["errors"]:
        print(f"  ERROR: {err}")
