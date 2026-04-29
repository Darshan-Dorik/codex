"""
log_filter.py — Log Compression / Filtering

Reduces output timelines to only the ticks relevant to failures
and violations, using a configurable time window around each event.

This keeps analysis payloads small and focused without losing
the context needed to understand what went wrong.
"""


def extract_window(timeline, center_ms, window_before_ms=200,
                   window_after_ms=200):
    """
    Extract timeline entries within a time window around a center point.

    Args:
        timeline         : list of {"time": int, ...} dicts
        center_ms        : int — the focal timestamp (failure/violation time)
        window_before_ms : int — how many ms before center to include
        window_after_ms  : int — how many ms after center to include

    Returns:
        list of timeline entries within [center - before, center + after]
    """
    lo = center_ms - window_before_ms
    hi = center_ms + window_after_ms
    return [entry for entry in timeline if lo <= entry["time"] <= hi]


def compress_timeline(timeline, focus_times, window_before_ms=200,
                      window_after_ms=200):
    """
    Compress a timeline by keeping only ticks near focus_times.

    Overlapping windows are merged (no duplicate entries).
    Entries are returned in time order.

    Args:
        timeline         : full list of timeline entry dicts
        focus_times      : list of int — timestamps to focus on
        window_before_ms : ms before each focus time to include
        window_after_ms  : ms after each focus time to include

    Returns:
        {
          "entries":       [...],   # filtered timeline entries (sorted, deduped)
          "total_ticks":   int,     # original tick count
          "kept_ticks":    int,     # ticks after compression
          "dropped_ticks": int,
          "focus_times":   [int, ...]
        }
    """
    if not focus_times:
        # Nothing to focus on — return empty (no relevant context)
        return {
            "entries":       [],
            "total_ticks":   len(timeline),
            "kept_ticks":    0,
            "dropped_ticks": len(timeline),
            "focus_times":   []
        }

    # Collect unique entries by time (use dict to deduplicate)
    kept = {}
    for t in focus_times:
        for entry in extract_window(timeline, t, window_before_ms,
                                    window_after_ms):
            kept[entry["time"]] = entry

    # Sort by time
    sorted_entries = sorted(kept.values(), key=lambda e: e["time"])

    return {
        "entries":       sorted_entries,
        "total_ticks":   len(timeline),
        "kept_ticks":    len(sorted_entries),
        "dropped_ticks": len(timeline) - len(sorted_entries),
        "focus_times":   sorted(set(focus_times))
    }


def compress_result_logs(result, window_before_ms=200, window_after_ms=200):
    """
    Compress the timeline of a single scenario result dict.

    Focus points are:
      - Times of assertion errors (extracted from error messages)
      - Times of property violations

    Args:
        result           : result dict from execute_scenarios()
        window_before_ms : ms before each focus time
        window_after_ms  : ms after each focus time

    Returns:
        compressed timeline dict from compress_timeline()
    """
    timeline = result.get("timeline", [])
    focus_times = []

    # Extract times from violation records
    for v in result.get("violations", []):
        focus_times.append(v["time"])

    # Extract times from assertion error messages ("At Xms: ...")
    import re
    for err in result.get("errors", []):
        m = re.search(r"At (\d+)ms", err)
        if m:
            focus_times.append(int(m.group(1)))

    return compress_timeline(timeline, focus_times,
                             window_before_ms, window_after_ms)


def print_compressed_log(compressed, scenario_name=""):
    """Print a compressed timeline in a readable format."""
    label = f" — {scenario_name}" if scenario_name else ""
    print(f"  Compressed log{label}:")
    print(f"    total_ticks  : {compressed['total_ticks']}")
    print(f"    kept_ticks   : {compressed['kept_ticks']}")
    print(f"    dropped_ticks: {compressed['dropped_ticks']}")
    print(f"    focus_times  : {compressed['focus_times']}")
    print()
    if compressed["entries"]:
        for entry in compressed["entries"]:
            marker = " <-- FOCUS" if entry["time"] in compressed["focus_times"] \
                     else ""
            print(f"    t={entry['time']:>5}ms | "
                  f"inputs={entry['inputs']} | "
                  f"outputs={entry['outputs']}{marker}")
    else:
        print("    (no entries)")


if __name__ == "__main__":
    from scenario_generator import generate_scenarios
    from scenario_template import expand_template
    from batch_executor import execute_scenarios_from_file
    from properties import make_property

    print("=" * 60)
    print("Phase 5 - Step 9: Log Compression / Filtering")
    print("=" * 60)

    prop_safety = make_property(
        "Y0 must not be True when X1 is True",
        lambda s: not (s["outputs"].get("Y0") is True and
                       s["inputs"].get("X1") is True)
    )

    # -------------------------------------------------------
    # Run shuttle_control.st — violation at t=300, 400, 500ms
    # Full simulation: 500ms / 100ms step = 5 ticks
    # -------------------------------------------------------
    partial = expand_template({
        "name": "ShuttleLog",
        "inputs": ["X0", "X1", "X2"],
        "timing": [300],
        "variations": [
            {"__initial__": {"X0": True}, "X0": True, "X1": True, "X2": False}
        ],
        "expected": []
    })

    batch = execute_scenarios_from_file(
        st_file="programs/shuttle_control.st",
        scenarios=partial,
        max_time_ms=500, step_ms=100,
        properties=[prop_safety]
    )

    result = batch["results"][0]
    timeline = result["timeline"]

    print(f"\nFull timeline ({len(timeline)} ticks):")
    for entry in timeline:
        print(f"  t={entry['time']:>5}ms | inputs={entry['inputs']} | "
              f"outputs={entry['outputs']}")

    # -------------------------------------------------------
    # Test 1: compress with window ±100ms around violations
    # -------------------------------------------------------
    print("\nTest 1 — compress_result_logs (window ±100ms):")
    compressed_100 = compress_result_logs(result,
                                          window_before_ms=100,
                                          window_after_ms=100)
    print_compressed_log(compressed_100, result["scenario"])

    # -------------------------------------------------------
    # Test 2: compress with tight window ±0ms (exact ticks only)
    # -------------------------------------------------------
    print("Test 2 — compress_result_logs (window ±0ms, exact ticks only):")
    compressed_0 = compress_result_logs(result,
                                        window_before_ms=0,
                                        window_after_ms=0)
    print_compressed_log(compressed_0, result["scenario"])

    # -------------------------------------------------------
    # Test 3: no violations — empty compressed log
    # -------------------------------------------------------
    print("Test 3 — no violations (empty focus → empty log):")
    gen_clean = generate_scenarios(
        inputs=["X0", "X1"], timing=[300], max_scenarios=1, base_name="Clean"
    )
    # Only X0=F, X1=F — no violations
    batch_clean = execute_scenarios_from_file(
        st_file="programs/motor_start.st",
        scenarios=gen_clean["scenarios"],
        max_time_ms=500, step_ms=100,
        properties=[prop_safety]
    )
    result_clean = batch_clean["results"][0]
    compressed_clean = compress_result_logs(result_clean)
    print_compressed_log(compressed_clean, result_clean["scenario"])

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("--- Assertions ---")

    # Test 1: violations at 300, 400, 500 — window ±100ms keeps 200-500
    assert compressed_100["total_ticks"]   == 5,  "total ticks = 5"
    assert compressed_100["kept_ticks"]    <= 5,  "kept <= total"
    assert compressed_100["kept_ticks"]    >= 3,  "at least 3 ticks kept"
    assert compressed_100["dropped_ticks"] >= 0,  "dropped >= 0"
    # All focus times present in entries
    entry_times = {e["time"] for e in compressed_100["entries"]}
    for ft in compressed_100["focus_times"]:
        assert ft in entry_times, f"focus time {ft} must be in entries"
    print(f"  PASS — Test 1: {compressed_100['kept_ticks']}/{compressed_100['total_ticks']} "
          f"ticks kept (window ±100ms)")

    # Test 2: exact ticks only — 3 focus times, 3 entries
    assert compressed_0["kept_ticks"] == 3,  "exact: 3 violation ticks"
    assert compressed_0["dropped_ticks"] == 2
    print(f"  PASS — Test 2: {compressed_0['kept_ticks']} ticks kept (window ±0ms)")

    # Test 3: no violations → 0 entries
    assert compressed_clean["kept_ticks"]    == 0, "no violations → 0 kept"
    assert compressed_clean["dropped_ticks"] == 5, "all 5 dropped"
    print(f"  PASS — Test 3: no violations → 0 ticks kept")
