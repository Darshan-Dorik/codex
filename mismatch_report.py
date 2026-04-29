"""
mismatch_report.py — Mismatch Summary Report

Aggregates mismatches from a diff result into a structured summary,
grouped by signal and time.

Summary schema:
{
  "total_mismatches": int,
  "total_compared":   int,
  "mismatch_rate":    float,   # percentage
  "signals": {
    "<signal>": {
      "count":  int,
      "times":  [int, ...],
      "details": [{"time": int, "sim": bool, "real": bool}, ...]
    }
  },
  "first_mismatch_time": int | None,
  "last_mismatch_time":  int | None
}
"""

from trace_diff import diff_traces


def build_mismatch_summary(diff_result):
    """
    Aggregate a diff result into a structured mismatch summary.

    Args:
        diff_result : dict — from diff_traces()

    Returns:
        summary dict
    """
    mismatches     = diff_result["mismatches"]
    total_compared = diff_result["total_compared"]
    total_mm       = len(mismatches)

    signals = {}
    for m in mismatches:
        sig = m["signal"]
        if sig not in signals:
            signals[sig] = {"count": 0, "times": [], "details": []}
        signals[sig]["count"] += 1
        signals[sig]["times"].append(m["time"])
        signals[sig]["details"].append({
            "time": m["time"],
            "sim":  m["sim"],
            "real": m["real"]
        })

    times = [m["time"] for m in mismatches]

    rate = round(total_mm / total_compared * 100, 1) if total_compared else 0.0

    return {
        "total_mismatches":    total_mm,
        "total_compared":      total_compared,
        "mismatch_rate":       rate,
        "signals":             signals,
        "first_mismatch_time": min(times) if times else None,
        "last_mismatch_time":  max(times) if times else None
    }


def print_mismatch_summary(summary):
    """Print the mismatch summary in a readable format."""
    print("=" * 55)
    print("  MISMATCH SUMMARY REPORT")
    print("=" * 55)
    print(f"  total_compared   : {summary['total_compared']}")
    print(f"  total_mismatches : {summary['total_mismatches']}")
    print(f"  mismatch_rate    : {summary['mismatch_rate']}%")
    print(f"  first_mismatch   : {summary['first_mismatch_time']}ms")
    print(f"  last_mismatch    : {summary['last_mismatch_time']}ms")

    if summary["signals"]:
        print()
        print("  Per-signal breakdown:")
        for sig, data in summary["signals"].items():
            print(f"    {sig}: {data['count']} mismatch(es) "
                  f"at t={data['times']}")
            for d in data["details"]:
                print(f"      t={d['time']}ms  sim={d['sim']}  "
                      f"real={d['real']}")
    else:
        print("\n  No mismatches.")
    print("=" * 55)


if __name__ == "__main__":
    import json, os
    from sim_trace import load_sim_trace
    from real_trace import create_mock_real_trace

    print("=" * 60)
    print("Phase 7 - Step 8: Mismatch Summary Report")
    print("=" * 60)

    sim_trace_path = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found")
        exit(1)

    sim_trace = load_sim_trace(sim_trace_path)

    # -------------------------------------------------------
    # Test 1: no mismatches
    # -------------------------------------------------------
    print("\nTest 1 — No mismatches:")
    real_clean = create_mock_real_trace(sim_trace)
    diff1 = diff_traces(sim_trace, real_clean, tolerance_ms=0)
    summary1 = build_mismatch_summary(diff1)
    print_mismatch_summary(summary1)

    # -------------------------------------------------------
    # Test 2: multiple mismatches across signals and times
    # -------------------------------------------------------
    print("\nTest 2 — Multiple mismatches:")

    def inject_mismatches(signals, time):
        signals = dict(signals)
        if time == 300 and "Y0" in signals:
            signals["Y0"] = not signals["Y0"]
        if time == 500 and "X0" in signals:
            signals["X0"] = not signals["X0"]
        if time == 500 and "Y0" in signals:
            signals["Y0"] = not signals["Y0"]
        if time == 600 and "Y0" in signals:
            signals["Y0"] = not signals["Y0"]
        return signals

    real_noisy = create_mock_real_trace(sim_trace,
                                        noise_fn=inject_mismatches)
    diff2 = diff_traces(sim_trace, real_noisy, tolerance_ms=0)
    summary2 = build_mismatch_summary(diff2)
    print_mismatch_summary(summary2)

    # Print JSON
    print("\n--- Summary JSON ---")
    print(json.dumps(summary2, indent=2))

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Test 1: clean
    assert summary1["total_mismatches"]    == 0
    assert summary1["mismatch_rate"]       == 0.0
    assert summary1["first_mismatch_time"] is None
    assert summary1["signals"]             == {}
    print("  PASS — Test 1: 0 mismatches, rate=0%, no signal entries")

    # Test 2: 4 mismatches (Y0×3, X0×1)
    assert summary2["total_mismatches"]    == 4
    assert "Y0" in summary2["signals"]
    assert "X0" in summary2["signals"]
    assert summary2["signals"]["Y0"]["count"] == 3
    assert summary2["signals"]["X0"]["count"] == 1
    assert summary2["first_mismatch_time"] == 300
    assert summary2["last_mismatch_time"]  == 600
    print("  PASS — Test 2: 4 mismatches, Y0×3 X0×1, "
          "first=300ms last=600ms")

    rate = summary2["mismatch_rate"]
    assert 0 < rate < 100,                 "rate must be between 0 and 100"
    print(f"  PASS — mismatch_rate={rate}% (non-zero, < 100%)")
