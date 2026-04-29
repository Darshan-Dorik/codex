"""
readable_report.py — Human-Readable Mismatch Report

Uses the IO map to translate symbolic signal names into human-readable
descriptions and produces plain-English mismatch messages.

Example output:
  "At 300ms: Main Motor expected ON but was OFF"
  "At 500ms: Start Button expected ON but was OFF"
"""

from io_map import IOMap, make_loom_io_map
from mismatch_report import build_mismatch_summary
from trace_diff import diff_traces


def _signal_state(value):
    """Convert bool to ON/OFF string."""
    return "ON" if value else "OFF"


def format_mismatch_message(mismatch, io_map):
    """
    Format a single mismatch dict into a human-readable string.

    Args:
        mismatch : dict — {"time", "signal", "sim", "real"}
        io_map   : IOMap

    Returns:
        str — e.g. "At 300ms: Main Motor expected ON but was OFF"
    """
    signal_name = io_map.name(mismatch["signal"])
    sim_state   = _signal_state(mismatch["sim"])
    real_state  = _signal_state(mismatch["real"])
    return (f"At {mismatch['time']}ms: {signal_name} "
            f"expected {sim_state} but was {real_state}")


def build_readable_report(diff_result, io_map=None):
    """
    Build a human-readable report from a diff result.

    Args:
        diff_result : dict — from diff_traces()
        io_map      : IOMap | None — if None, uses make_loom_io_map()

    Returns:
        {
          "messages":  [str, ...],   # one message per mismatch
          "summary":   str,          # one-line overall summary
          "has_mismatches": bool
        }
    """
    if io_map is None:
        io_map = make_loom_io_map()

    mismatches = diff_result["mismatches"]
    mm_summary = build_mismatch_summary(diff_result)

    messages = [
        format_mismatch_message(m, io_map) for m in mismatches
    ]

    if not mismatches:
        summary = "All signals matched — simulation and real machine agree."
    else:
        total = mm_summary["total_mismatches"]
        rate  = mm_summary["mismatch_rate"]
        first = mm_summary["first_mismatch_time"]
        last  = mm_summary["last_mismatch_time"]
        sigs  = list(mm_summary["signals"].keys())
        sig_names = [io_map.name(s) for s in sigs]
        summary = (
            f"{total} mismatch(es) detected ({rate}%) "
            f"between t={first}ms and t={last}ms. "
            f"Affected signals: {', '.join(sig_names)}."
        )

    return {
        "messages":       messages,
        "summary":        summary,
        "has_mismatches": len(mismatches) > 0
    }


def print_readable_report(report):
    """Print the human-readable report."""
    print("=" * 60)
    print("  HUMAN-READABLE MISMATCH REPORT")
    print("=" * 60)
    print(f"\n  Summary: {report['summary']}")

    if report["messages"]:
        print("\n  Details:")
        for msg in report["messages"]:
            print(f"    • {msg}")
    print("=" * 60)


if __name__ == "__main__":
    import os
    from sim_trace import load_sim_trace
    from real_trace import create_mock_real_trace

    print("=" * 60)
    print("Phase 7 - Step 9: Human-Readable Report")
    print("=" * 60)

    sim_trace_path = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found")
        exit(1)

    sim_trace = load_sim_trace(sim_trace_path)
    io_map    = make_loom_io_map()

    # -------------------------------------------------------
    # Test 1: no mismatches
    # -------------------------------------------------------
    print("\nTest 1 — No mismatches:")
    real_clean = create_mock_real_trace(sim_trace)
    diff1 = diff_traces(sim_trace, real_clean, tolerance_ms=0)
    report1 = build_readable_report(diff1, io_map)
    print_readable_report(report1)

    # -------------------------------------------------------
    # Test 2: realistic mismatches
    # -------------------------------------------------------
    print("\nTest 2 — Realistic mismatches:")

    def inject_realistic(signals, time):
        signals = dict(signals)
        # Motor stays ON after fault (Y0 should be OFF at t=500+)
        if time in (500, 600) and "Y0" in signals:
            signals["Y0"] = True   # real machine didn't stop
        # Position indicator wrong at t=300
        if time == 300 and "Y1" in signals:
            signals["Y1"] = True   # real shows position reached early
        return signals

    real_noisy = create_mock_real_trace(sim_trace,
                                        noise_fn=inject_realistic)
    diff2 = diff_traces(sim_trace, real_noisy, tolerance_ms=0)
    report2 = build_readable_report(diff2, io_map)
    print_readable_report(report2)

    # -------------------------------------------------------
    # Test 3: unknown signal (not in IO map)
    # -------------------------------------------------------
    print("\nTest 3 — Unknown signal (falls back to symbol):")
    diff3_mismatches = [{"time": 400, "signal": "X9",
                         "sim": True, "real": False}]
    msg = format_mismatch_message(diff3_mismatches[0], io_map)
    print(f"  Message: {msg}")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Test 1: clean
    assert report1["has_mismatches"] is False
    assert "agree" in report1["summary"].lower()
    assert report1["messages"] == []
    print("  PASS — Test 1: no mismatches, summary says 'agree'")

    # Test 2: messages use human names
    assert report2["has_mismatches"] is True
    assert len(report2["messages"]) > 0
    for msg in report2["messages"]:
        # Must contain human-readable name, not raw symbol
        assert "Y0" not in msg or "Main Motor" in msg, \
            f"raw symbol in message: {msg}"
    print(f"  PASS — Test 2: {len(report2['messages'])} message(s), "
          f"all use human-readable names")
    for msg in report2["messages"]:
        print(f"    • {msg}")

    # Test 3: unknown signal falls back to symbol
    msg_x9 = format_mismatch_message(diff3_mismatches[0], io_map)
    assert "X9" in msg_x9,  "unknown signal uses symbol as fallback"
    print("  PASS — Test 3: unknown signal falls back to symbol 'X9'")

    # Summary contains signal names
    assert "Main Motor" in report2["summary"] or \
           "Position Indicator" in report2["summary"], \
        "summary must contain human-readable signal names"
    print("  PASS — summary contains human-readable signal names")
