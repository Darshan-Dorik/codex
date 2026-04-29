"""
trace_recorder.py — Real Trace Recorder

Records signals from a real data adapter over a specified duration
and saves the result as a real_trace.json file.

SAFETY:
  - READ-ONLY: only reads from the adapter, never writes.
  - All recorded data is logged for traceability.
  - No feedback into the real machine.

Two recording modes:
  - "timed"  : record for a fixed duration at fixed intervals
  - "stepped": record at explicit time steps (deterministic, for testing)
"""

import json
import time as time_module
from real_trace import validate_real_trace, save_real_trace


def record_trace_timed(adapter, duration_ms, interval_ms=100):
    """
    Record signals from the adapter for a fixed duration.

    Uses wall-clock time — suitable for real machine recording.

    Args:
        adapter     : adapter with read_signals() method
        duration_ms : int — total recording duration in ms
        interval_ms : int — sampling interval in ms

    Returns:
        list — real trace entries
    """
    trace = []
    start_wall = time_module.time()
    elapsed_ms = 0

    while elapsed_ms < duration_ms:
        signals = adapter.read_signals()
        trace.append({
            "time":    elapsed_ms,
            "signals": dict(signals)
        })

        time_module.sleep(interval_ms / 1000.0)
        elapsed_ms = int((time_module.time() - start_wall) * 1000)

    return trace


def record_trace_stepped(adapter, time_steps_ms):
    """
    Record signals at explicit time steps (deterministic).

    Does NOT use wall-clock time — suitable for testing and replay.
    Calls adapter.read_signals() once per step.

    Args:
        adapter       : adapter with read_signals() method
        time_steps_ms : list of int — timestamps to record at

    Returns:
        list — real trace entries
    """
    trace = []
    for t in sorted(time_steps_ms):
        signals = adapter.read_signals()
        trace.append({
            "time":    t,
            "signals": dict(signals)
        })
    return trace


def record_and_save(adapter, time_steps_ms, filepath="outputs/real_trace.json"):
    """
    Record a stepped trace and save it to disk.

    Args:
        adapter       : adapter with read_signals() method
        time_steps_ms : list of int — timestamps to record at
        filepath      : str — output file path

    Returns:
        list — the recorded trace
    """
    trace = record_trace_stepped(adapter, time_steps_ms)
    save_real_trace(trace, filepath)
    return trace


if __name__ == "__main__":
    import os
    from real_adapter import MockRealAdapter
    from sim_trace import load_sim_trace

    print("=" * 60)
    print("Phase 7 - Step 5: Real Trace Recorder")
    print("=" * 60)

    # Load sim trace to use as playback source
    sim_trace_path = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found — run sim_trace.py first")
        exit(1)

    sim_trace = load_sim_trace(sim_trace_path)
    time_steps = [e["time"] for e in sim_trace]

    # -------------------------------------------------------
    # Test 1: record from static adapter (stepped)
    # -------------------------------------------------------
    print("\nTest 1 — Stepped recording from static adapter:")
    static_adapter = MockRealAdapter(mode="static")
    trace_static = record_trace_stepped(static_adapter, time_steps)

    print(f"  Recorded {len(trace_static)} entries")
    for entry in trace_static:
        print(f"  t={entry['time']:>5}ms | {entry['signals']}")

    # -------------------------------------------------------
    # Test 2: record from playback adapter (matches sim trace)
    # -------------------------------------------------------
    print("\nTest 2 — Stepped recording from playback adapter:")

    # Build playback trace from sim trace (merge inputs+outputs)
    from real_trace import create_mock_real_trace
    playback_data = create_mock_real_trace(sim_trace)

    playback_adapter = MockRealAdapter(mode="playback",
                                       playback_trace=playback_data)
    trace_playback = record_trace_stepped(playback_adapter, time_steps)

    print(f"  Recorded {len(trace_playback)} entries")
    for entry in trace_playback:
        print(f"  t={entry['time']:>5}ms | {entry['signals']}")

    # -------------------------------------------------------
    # Test 3: save and verify file content
    # -------------------------------------------------------
    print("\nTest 3 — Save and verify file:")
    output_path = "outputs/real_trace.json"
    saved_trace = record_and_save(playback_adapter, time_steps, output_path)

    print(f"  Saved to: {output_path}")
    with open(output_path) as f:
        loaded = json.load(f)
    print(f"  Reloaded {len(loaded)} entries")
    print(f"  First entry: {loaded[0]}")
    print(f"  Last entry : {loaded[-1]}")

    # -------------------------------------------------------
    # Test 4: validate recorded trace
    # -------------------------------------------------------
    print("\nTest 4 — Validate recorded trace:")
    from real_trace import validate_real_trace
    validation = validate_real_trace(trace_playback)
    print(f"  valid  : {validation['valid']}")
    print(f"  errors : {validation['errors']}")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert len(trace_static)   == len(time_steps), "static: correct tick count"
    assert len(trace_playback) == len(time_steps), "playback: correct tick count"
    print(f"  PASS — both traces have {len(time_steps)} entries")

    # Time steps match exactly
    for i, t in enumerate(time_steps):
        assert trace_static[i]["time"]   == t, f"static time mismatch at {i}"
        assert trace_playback[i]["time"] == t, f"playback time mismatch at {i}"
    print("  PASS — all timestamps match expected steps")

    # Each entry has 'signals' dict
    for entry in trace_playback:
        assert "signals" in entry,          "must have signals key"
        assert isinstance(entry["signals"], dict)
    print("  PASS — all entries have signals dict")

    # Validation passes
    assert validation["valid"] is True,     "trace must be valid"
    print("  PASS — recorded trace validates correctly")

    # File exists and round-trips
    assert os.path.exists(output_path),     "file must exist"
    assert len(loaded) == len(trace_playback), "file has correct entry count"
    print(f"  PASS — {output_path} saved and verified")
