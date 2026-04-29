"""
trace_diff.py — Trace Diff Engine

Compares aligned sim and real trace pairs signal-by-signal,
detecting mismatches between expected (sim) and actual (real) values.

Mismatch format:
{
  "time":   int,    # sim time of the mismatch
  "signal": str,    # signal name (e.g. "Y0")
  "sim":    bool,   # value in simulation
  "real":   bool    # value in real trace
}
"""

from trace_aligner import align_traces


def diff_traces(sim_trace, real_trace, tolerance_ms=50,
                signals_to_check=None):
    """
    Align and diff two traces, returning all signal mismatches.

    Args:
        sim_trace        : list — simulation trace entries
        real_trace       : list — real trace entries
        tolerance_ms     : int  — alignment tolerance
        signals_to_check : list | None — specific signals to compare;
                           if None, compares all signals present in sim

    Returns:
        {
          "mismatches":     [...],   # list of mismatch dicts
          "alignment":      {...},   # full alignment result
          "total_compared": int,     # total signal comparisons made
          "total_mismatches": int
        }
    """
    alignment = align_traces(sim_trace, real_trace, tolerance_ms)
    mismatches = []
    total_compared = 0

    for pair in alignment["aligned"]:
        t_sim    = pair["time_sim"]
        sim_entry  = pair["sim"]
        real_entry = pair["real"]

        # Build flat sim signal dict (inputs + outputs combined)
        sim_signals = {}
        sim_signals.update(sim_entry.get("inputs", {}))
        sim_signals.update(sim_entry.get("outputs", {}))

        real_signals = real_entry.get("signals", {})

        # Determine which signals to compare
        if signals_to_check:
            compare_keys = signals_to_check
        else:
            compare_keys = list(sim_signals.keys())

        for key in compare_keys:
            sim_val  = sim_signals.get(key)
            real_val = real_signals.get(key)

            # Only compare if both sides have the signal
            if sim_val is None or real_val is None:
                continue

            total_compared += 1

            if sim_val != real_val:
                mismatches.append({
                    "time":   t_sim,
                    "signal": key,
                    "sim":    sim_val,
                    "real":   real_val
                })

    return {
        "mismatches":       mismatches,
        "alignment":        alignment,
        "total_compared":   total_compared,
        "total_mismatches": len(mismatches)
    }


def print_diff(diff_result):
    """Print diff results in a readable format."""
    a = diff_result["alignment"]
    print(f"  Aligned pairs   : {a['total_aligned']} / {a['total_sim']}")
    print(f"  Total compared  : {diff_result['total_compared']} signal checks")
    print(f"  Total mismatches: {diff_result['total_mismatches']}")

    if diff_result["mismatches"]:
        print()
        print(f"  {'Time':>8}  {'Signal':10}  {'Sim':>6}  {'Real':>6}")
        print("  " + "-" * 38)
        for m in diff_result["mismatches"]:
            print(f"  {m['time']:>7}ms  {m['signal']:10}  "
                  f"{str(m['sim']):>6}  {str(m['real']):>6}")
    else:
        print("  No mismatches detected.")


if __name__ == "__main__":
    import os
    from sim_trace import load_sim_trace
    from real_trace import create_mock_real_trace

    print("=" * 60)
    print("Phase 7 - Step 7: Trace Diff Engine")
    print("=" * 60)

    sim_trace_path = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found — run sim_trace.py first")
        exit(1)

    sim_trace = load_sim_trace(sim_trace_path)

    # -------------------------------------------------------
    # Test 1: identical traces — no mismatches
    # -------------------------------------------------------
    print("\nTest 1 — Identical traces (no mismatches expected):")
    real_clean = create_mock_real_trace(sim_trace)
    diff1 = diff_traces(sim_trace, real_clean, tolerance_ms=0)
    print_diff(diff1)

    # -------------------------------------------------------
    # Test 2: inject Y0 mismatch at t=300ms
    # -------------------------------------------------------
    print("\nTest 2 — Y0 flipped at t=300ms:")

    def flip_y0_at_300(signals, time):
        if time == 300 and "Y0" in signals:
            signals = dict(signals)
            signals["Y0"] = not signals["Y0"]
        return signals

    real_y0_flip = create_mock_real_trace(sim_trace, noise_fn=flip_y0_at_300)
    diff2 = diff_traces(sim_trace, real_y0_flip, tolerance_ms=0)
    print_diff(diff2)

    # -------------------------------------------------------
    # Test 3: multiple mismatches — X0 and Y0 at t=500ms
    # -------------------------------------------------------
    print("\nTest 3 — X0 and Y0 both wrong at t=500ms:")

    def flip_multi_at_500(signals, time):
        if time == 500:
            signals = dict(signals)
            if "X0" in signals:
                signals["X0"] = not signals["X0"]
            if "Y0" in signals:
                signals["Y0"] = not signals["Y0"]
        return signals

    real_multi = create_mock_real_trace(sim_trace, noise_fn=flip_multi_at_500)
    diff3 = diff_traces(sim_trace, real_multi, tolerance_ms=0)
    print_diff(diff3)

    # -------------------------------------------------------
    # Test 4: check only outputs (Y0) — ignore input mismatches
    # -------------------------------------------------------
    print("\nTest 4 — Check outputs only (signals_to_check=['Y0']):")
    diff4 = diff_traces(sim_trace, real_multi, tolerance_ms=0,
                        signals_to_check=["Y0"])
    print_diff(diff4)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert diff1["total_mismatches"] == 0,          "Test 1: no mismatches"
    assert diff1["total_compared"]   > 0,           "Test 1: comparisons made"
    print("  PASS — Test 1: 0 mismatches on identical traces")

    assert diff2["total_mismatches"] == 1,          "Test 2: exactly 1 mismatch"
    m = diff2["mismatches"][0]
    assert m["time"]   == 300,                      "Test 2: at t=300ms"
    assert m["signal"] == "Y0",                     "Test 2: signal Y0"
    assert m["sim"]    is True,                     "Test 2: sim=True"
    assert m["real"]   is False,                    "Test 2: real=False"
    print(f"  PASS — Test 2: 1 mismatch — "
          f"At {m['time']}ms: {m['signal']} sim={m['sim']} real={m['real']}")

    assert diff3["total_mismatches"] == 2,          "Test 3: 2 mismatches"
    signals_hit = {m["signal"] for m in diff3["mismatches"]}
    assert "X0" in signals_hit and "Y0" in signals_hit
    print("  PASS — Test 3: 2 mismatches (X0 and Y0 at t=500ms)")

    assert diff4["total_mismatches"] == 1,          "Test 4: only Y0 checked"
    assert diff4["mismatches"][0]["signal"] == "Y0"
    print("  PASS — Test 4: signals_to_check filter works (only Y0 checked)")
