"""
sim_trace.py — Simulation Trace Export

Runs a scenario through the existing simulation engine and exports
the full output timeline as a structured JSON trace file.

Trace format:
[
  {
    "time":    int,          # simulation time in ms
    "inputs":  {str: bool},  # PLC input snapshot at this tick
    "outputs": {str: bool}   # PLC output snapshot at this tick
  },
  ...
]

This is a READ-ONLY export of simulation data.
It does not interact with any real machine.
"""

import json
import io
import sys
import os

# Ensure all src subpackages are importable from root
for _subdir in ("src/core", "src/testing", "src/batch", "src/analysis", "src/ai"):
    _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _subdir)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def export_sim_trace(scenario, logic, max_time_ms=1000, step_ms=100,
                     wiring=None):
    """
    Run a scenario and return the output timeline as a trace list.

    Args:
        scenario    : dict  — scenario dict (initial_inputs, events, expected)
        logic       : list  — parsed PLC logic from parse_st()
        max_time_ms : int   — simulation duration in ms
        step_ms     : int   — tick size in ms
        wiring      : callable — optional loom wiring callback

    Returns:
        list of trace entry dicts
    """
    from test_harness import TestHarness

    harness = TestHarness()
    harness.load_scenario(scenario)

    # Suppress per-tick console output
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    harness.run(max_time_ms=max_time_ms, step_ms=step_ms,
                logic=logic, wiring=wiring)
    sys.stdout = old_stdout

    # Return a clean copy of the timeline
    return [
        {
            "time":    entry["time"],
            "inputs":  dict(entry["inputs"]),
            "outputs": dict(entry["outputs"])
        }
        for entry in harness.output_timeline
    ]


def save_sim_trace(trace, filepath="sim_trace.json"):
    """
    Save a simulation trace to a JSON file.

    Args:
        trace    : list — trace entries from export_sim_trace()
        filepath : str  — output file path
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2)


def load_sim_trace(filepath="sim_trace.json"):
    """Load a previously saved simulation trace from disk."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import os
    from st_loader import load_st_file
    from st_parser import parse_st

    print("=" * 60)
    print("Phase 7 - Step 2: Simulation Trace Export")
    print("=" * 60)

    # --- Scenario: motor start with fault injection ---
    scenario = {
        "name": "Motor Start Trace",
        "initial_inputs": {"X0": False, "X1": False},
        "events": [
            {"time": 200, "inputs": {"X0": True}},   # start at 200ms
            {"time": 500, "inputs": {"X1": True}},   # fault at 500ms
        ],
        "expected": []
    }

    st_code = load_st_file("programs/motor_start.st")
    logic   = parse_st(st_code)

    # --- Run and export ---
    # Scan period is 10ms (see src/shim/twin_runtime.py). Derivation of
    # this golden:
    #   entry count  700ms / 10ms          = 70 scans
    #   Y0 rises     t=200ms  X0 event; TestHarness applies events
    #                         BEFORE the scan in the same tick, so
    #                         there is no scan of latency
    #   Y0 falls     t=500ms  X1 event, same rule
    #   Y0 True      200..490ms            = 30 scans
    #   Y0 False     10..190, 500..700ms   = 19 + 21 = 40 scans
    SCAN_PERIOD_MS = 10
    trace = export_sim_trace(scenario, logic, max_time_ms=700,
                             step_ms=SCAN_PERIOD_MS)

    print(f"\nTrace captured: {len(trace)} ticks")
    print("\nTrace entries:")
    for entry in trace:
        print(f"  t={entry['time']:>5}ms | "
              f"inputs={entry['inputs']} | "
              f"outputs={entry['outputs']}")

    # --- Save to file ---
    output_path = "outputs/sim_trace.json"
    save_sim_trace(trace, output_path)
    print(f"\nTrace saved to: {output_path}")

    # --- Reload and verify round-trip ---
    loaded = load_sim_trace(output_path)
    print(f"Reloaded {len(loaded)} entries from disk")

    # --- Assertions ---
    print("\n--- Assertions ---")

    assert len(trace) == 70,        "70 scans (10ms to 700ms @ 10ms)"
    print(f"  PASS — {len(trace)} scans captured "
          f"(700ms / {SCAN_PERIOD_MS}ms)")

    # Edge timing, derived above — these are the numbers that make the
    # entry count meaningful rather than just larger.
    rise = next(e["time"] for e in trace if e["outputs"].get("Y0"))
    fall = next(e["time"] for e in trace
                if e["time"] > rise and not e["outputs"].get("Y0"))
    assert rise == 200, f"Y0 must rise on the X0 event tick, got {rise}"
    assert fall == 500, f"Y0 must fall on the X1 event tick, got {fall}"
    print(f"  PASS — Y0 rises t={rise}ms, falls t={fall}ms "
          f"(0 scans latency; events precede the scan)")

    # Before start command: Y0 should be False
    t100 = next(e for e in trace if e["time"] == 100)
    assert t100["outputs"].get("Y0") is False,  "t=100ms: Y0 must be False"
    print("  PASS — t=100ms: Y0=False (before start)")

    # After start, before fault: Y0 should be True
    t300 = next(e for e in trace if e["time"] == 300)
    assert t300["outputs"].get("Y0") is True,   "t=300ms: Y0 must be True"
    print("  PASS — t=300ms: Y0=True (running)")

    # After fault: Y0 should be False
    t600 = next(e for e in trace if e["time"] == 600)
    assert t600["outputs"].get("Y0") is False,  "t=600ms: Y0 must be False"
    print("  PASS — t=600ms: Y0=False (fault active)")

    # Round-trip
    assert loaded == trace,                     "round-trip must be identical"
    print("  PASS — JSON round-trip identical")

    # File exists
    assert os.path.exists(output_path),         "file must exist on disk"
    print(f"  PASS — {output_path} exists on disk")
