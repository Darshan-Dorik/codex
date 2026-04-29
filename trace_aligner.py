"""
trace_aligner.py — Trace Alignment Engine

Aligns a simulation trace and a real trace by time, handling small
timing offsets with a configurable tolerance window.

Alignment strategy:
  For each sim trace entry at time T, find the real trace entry
  whose time is closest to T and within ±tolerance_ms.
  If no real entry falls within tolerance, the sim entry is unmatched.

Output:
  A list of aligned pairs:
  [
    {
      "time_sim":  int,
      "time_real": int,
      "offset_ms": int,          # real_time - sim_time
      "sim":       {...},        # full sim entry
      "real":      {...}         # full real entry
    },
    ...
  ]
  Plus lists of unmatched sim and real entries.
"""


def align_traces(sim_trace, real_trace, tolerance_ms=50):
    """
    Align sim_trace and real_trace entries by time.

    Args:
        sim_trace    : list — simulation trace entries
                       (each has "time", "inputs", "outputs")
        real_trace   : list — real trace entries
                       (each has "time", "signals")
        tolerance_ms : int  — max allowed time offset for a match

    Returns:
        {
          "aligned":          [...],   # matched pairs
          "unmatched_sim":    [...],   # sim entries with no real match
          "unmatched_real":   [...],   # real entries with no sim match
          "total_sim":        int,
          "total_real":       int,
          "total_aligned":    int,
          "tolerance_ms":     int
        }
    """
    aligned         = []
    unmatched_sim   = []
    used_real_times = set()

    for sim_entry in sim_trace:
        t_sim = sim_entry["time"]

        # Find closest real entry within tolerance
        best_real  = None
        best_delta = None

        for real_entry in real_trace:
            t_real = real_entry["time"]
            if t_real in used_real_times:
                continue
            delta = abs(t_real - t_sim)
            if delta <= tolerance_ms:
                if best_delta is None or delta < best_delta:
                    best_real  = real_entry
                    best_delta = delta

        if best_real is not None:
            used_real_times.add(best_real["time"])
            aligned.append({
                "time_sim":  t_sim,
                "time_real": best_real["time"],
                "offset_ms": best_real["time"] - t_sim,
                "sim":       sim_entry,
                "real":      best_real
            })
        else:
            unmatched_sim.append(sim_entry)

    # Real entries that were never matched
    unmatched_real = [
        e for e in real_trace if e["time"] not in used_real_times
    ]

    return {
        "aligned":        aligned,
        "unmatched_sim":  unmatched_sim,
        "unmatched_real": unmatched_real,
        "total_sim":      len(sim_trace),
        "total_real":     len(real_trace),
        "total_aligned":  len(aligned),
        "tolerance_ms":   tolerance_ms
    }


def print_alignment(result):
    """Print aligned pairs in a readable format."""
    print(f"  Alignment result:")
    print(f"    total_sim     : {result['total_sim']}")
    print(f"    total_real    : {result['total_real']}")
    print(f"    total_aligned : {result['total_aligned']}")
    print(f"    unmatched_sim : {len(result['unmatched_sim'])}")
    print(f"    unmatched_real: {len(result['unmatched_real'])}")
    print(f"    tolerance_ms  : {result['tolerance_ms']}")
    print()
    print(f"  {'SimTime':>8}  {'RealTime':>9}  {'Offset':>7}  "
          f"{'Sim signals':30}  Real signals")
    print("  " + "-" * 80)
    for pair in result["aligned"]:
        sim_sigs  = {**pair["sim"].get("inputs", {}),
                     **pair["sim"].get("outputs", {})}
        real_sigs = pair["real"].get("signals", {})
        offset    = f"{pair['offset_ms']:+d}ms"
        print(f"  {pair['time_sim']:>7}ms  {pair['time_real']:>8}ms  "
              f"{offset:>7}  {str(sim_sigs):30}  {real_sigs}")

    if result["unmatched_sim"]:
        print(f"\n  Unmatched sim entries:")
        for e in result["unmatched_sim"]:
            print(f"    t={e['time']}ms")

    if result["unmatched_real"]:
        print(f"\n  Unmatched real entries:")
        for e in result["unmatched_real"]:
            print(f"    t={e['time']}ms")


if __name__ == "__main__":
    import os
    from sim_trace import load_sim_trace
    from real_trace import load_real_trace, create_mock_real_trace

    print("=" * 60)
    print("Phase 7 - Step 6: Trace Alignment Engine")
    print("=" * 60)

    sim_trace_path  = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found — run sim_trace.py first")
        exit(1)

    sim_trace = load_sim_trace(sim_trace_path)

    # -------------------------------------------------------
    # Test 1: perfect alignment (same timestamps)
    # -------------------------------------------------------
    print("\nTest 1 — Perfect alignment (same timestamps):")
    real_trace_exact = create_mock_real_trace(sim_trace)
    result1 = align_traces(sim_trace, real_trace_exact, tolerance_ms=0)
    print_alignment(result1)

    # -------------------------------------------------------
    # Test 2: offset alignment (real trace shifted +25ms)
    # -------------------------------------------------------
    print("\nTest 2 — Offset alignment (real trace +25ms, tolerance=50ms):")
    real_trace_offset = [
        {"time": e["time"] + 25, "signals": e["signals"]}
        for e in real_trace_exact
    ]
    result2 = align_traces(sim_trace, real_trace_offset, tolerance_ms=50)
    print_alignment(result2)

    # -------------------------------------------------------
    # Test 3: tolerance too tight — some entries unmatched
    # -------------------------------------------------------
    print("\nTest 3 — Tight tolerance (real +25ms, tolerance=10ms):")
    result3 = align_traces(sim_trace, real_trace_offset, tolerance_ms=10)
    print_alignment(result3)

    # -------------------------------------------------------
    # Test 4: real trace missing one entry
    # -------------------------------------------------------
    print("\nTest 4 — Real trace missing t=300ms entry:")
    real_trace_missing = [e for e in real_trace_exact if e["time"] != 300]
    result4 = align_traces(sim_trace, real_trace_missing, tolerance_ms=0)
    print_alignment(result4)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Test 1: all 7 aligned, 0 unmatched
    assert result1["total_aligned"]    == 7, "perfect: all 7 aligned"
    assert len(result1["unmatched_sim"])  == 0
    assert len(result1["unmatched_real"]) == 0
    print("  PASS — Test 1: perfect alignment, 7/7 matched")

    # Test 2: all 7 aligned with +25ms offset
    assert result2["total_aligned"]    == 7, "offset: all 7 aligned"
    assert all(p["offset_ms"] == 25 for p in result2["aligned"])
    print("  PASS — Test 2: offset alignment, all offsets = +25ms")

    # Test 3: tight tolerance — 0 matched (25ms > 10ms tolerance)
    assert result3["total_aligned"]    == 0, "tight: 0 aligned"
    assert len(result3["unmatched_sim"]) == 7
    print("  PASS — Test 3: tight tolerance, 0/7 matched")

    # Test 4: 6 aligned, 1 unmatched sim (t=300ms)
    assert result4["total_aligned"]    == 6, "missing: 6 aligned"
    assert len(result4["unmatched_sim"]) == 1
    assert result4["unmatched_sim"][0]["time"] == 300
    print("  PASS — Test 4: missing entry, t=300ms unmatched")
