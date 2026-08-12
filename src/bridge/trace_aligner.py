"""
trace_aligner.py — Trace Alignment Engine

Aligns a simulation trace and a real trace by time, handling small
timing offsets with a configurable tolerance window.

Alignment strategy:
  For each sim trace entry at time T, find the real trace entry
  whose time is closest to T and within ±tolerance_ms.
  If no real entry falls within tolerance, the sim entry is unmatched.
  A real entry is consumed by at most one sim entry (greedy, in
  ascending sim-time order); ties are broken toward the earlier
  real timestamp.

  Greedy matching alone lets an earlier sim entry consume a real
  entry that its successor matches more exactly, which cascades: one
  dropped sample re-pairs every entry after it. A one-step steal-back
  (k=1) prevents this — see align_traces.

READING THE RESULT
------------------
total_aligned is not a health metric. A cascaded alignment reports
every entry matched while pairing each sim entry with its neighbour's
sample. Read result["offsets"] instead — specifically
offsets["cascade_suspected"], which distinguishes offsets that are
CLAMPED (a consistent whole-sample shift; never benign) from ones
that are SCATTERED (jitter around zero; expected on the
arrival-timestamp path).

Both traces are sorted by timestamp on ingest. Duplicate timestamps
are counted and reported but never raise — a collector polling faster
than its clock resolution produces them legitimately.

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
  Plus lists of unmatched sim and real entries, duplicate-timestamp
  counters, and any provenance warnings.

TIMESTAMP PROVENANCE
--------------------
A timestamp without its provenance is ambiguous. A trace may declare
how its timestamps were produced by wrapping its entries:

    {"provenance": {"timestamp": TS_SCAN}, "entries": [...]}

  TS_SCAN    — the timestamp IS the PLC scan time, read from the
               device alongside the data (e.g. the shim's sim-time
               registers). Exact; tolerance 0 is meaningful.
  TS_ARRIVAL — the timestamp was assigned when the sample arrived at
               the collector. Carries poll phase and network jitter;
               tolerance 0 is never correct and is refused.
  TS_UNKNOWN — a bare list with no declaration (legacy traces).
               Permitted for backward compatibility, but warned.

Bare lists are still accepted everywhere and are treated as
TS_UNKNOWN, so existing traces and goldens keep working unchanged.
"""

# ---------------------------------------------------------------------------
# Timestamp provenance
# ---------------------------------------------------------------------------

TS_SCAN    = "scan_timestamp"
TS_ARRIVAL = "arrival_timestamp"
TS_UNKNOWN = "unknown"

_VALID_PROVENANCE = (TS_SCAN, TS_ARRIVAL, TS_UNKNOWN)


def wrap_trace(entries, timestamp_provenance, **extra):
    """
    Wrap a bare entry list with its timestamp provenance.

    Producers of traces (the Modbus shim, the platform repo's
    real_adapter) should emit this shape rather than a bare list.

    Args:
        entries              : list — trace entries
        timestamp_provenance : str  — TS_SCAN | TS_ARRIVAL | TS_UNKNOWN
        **extra              : additional provenance fields (device,
                               program, validator, ...)

    Returns:
        {"provenance": {"timestamp": str, ...}, "entries": [...]}
    """
    if timestamp_provenance not in _VALID_PROVENANCE:
        raise ValueError(
            f"unknown timestamp provenance: {timestamp_provenance!r} "
            f"(expected one of {_VALID_PROVENANCE})"
        )
    prov = {"timestamp": timestamp_provenance}
    prov.update(extra)
    return {"provenance": prov, "entries": list(entries)}


def unwrap_trace(trace):
    """
    Accept either a bare entry list or a wrapped trace.

    Returns:
        (entries, provenance_dict) — provenance["timestamp"] is always
        present, defaulting to TS_UNKNOWN for bare lists.
    """
    if isinstance(trace, dict):
        entries = trace.get("entries", [])
        prov    = dict(trace.get("provenance", {}))
        prov.setdefault("timestamp", TS_UNKNOWN)
        return entries, prov
    return trace, {"timestamp": TS_UNKNOWN}


def _flat_signals(entry):
    """
    Flatten one trace entry to {signal: value}.

    Sim entries carry separate "inputs"/"outputs"; real entries carry
    a combined "signals". Outputs win over inputs on key collision,
    matching diff_traces.
    """
    flat = {}
    flat.update(entry.get("inputs", {}))
    flat.update(entry.get("outputs", {}))
    flat.update(entry.get("signals", {}))
    return flat


def _count_duplicate_timestamps(entries):
    """Return how many entries share a timestamp with an earlier entry."""
    seen = set()
    dupes = 0
    for e in entries:
        t = e["time"]
        if t in seen:
            dupes += 1
        else:
            seen.add(t)
    return dupes


# ---------------------------------------------------------------------------
# Transition compression
# ---------------------------------------------------------------------------

def compress_to_transitions(trace, signals=None):
    """
    Reduce a trace to the entries where a watched signal changed value.

    DISCRETE SIGNALS ONLY. Compression here is exact-equality based:
    an entry is kept only when some watched signal differs from the
    previous kept entry. On float signals nothing ever repeats exactly,
    so compression would be a silent no-op that looks like it worked.
    Float values are therefore rejected outright.

    Analog signals need deadband compression (keep a sample when it
    moves more than ±d from the last kept value, plus a max-gap
    heartbeat). That is a separate function — NOT IMPLEMENTED. The
    platform repo's signals are largely analog (melt pressure, motor
    load, specific energy), so this gap will need closing before
    transition-mode diffing is useful there.

    The first and last entries are always kept: the first carries the
    initial state, the last preserves the trace's end time (without it
    a trace ending mid-plateau silently loses its duration).

    Args:
        trace   : list | dict — bare entry list or wrapped trace
        signals : iterable | None — watched signal names. Default None
                  scans the whole trace for the union of signal keys,
                  which requires a full pass before compression can
                  begin. Pass an explicit set to compress in a single
                  streaming pass over a large trace.

    Returns:
        {
          "entries":        [...],  # kept entries, each with added
                                    # "held_from" / "held_until" (ms)
          "total_entries":  int,
          "kept_entries":   int,
          "dropped_entries":int,
          "signals":        [str, ...],   # watched set, sorted
          "provenance":     {...}
        }

    Raises:
        TypeError — if any watched signal carries a float value.
    """
    entries, prov = unwrap_trace(trace)

    if not entries:
        return {
            "entries":         [],
            "total_entries":   0,
            "kept_entries":    0,
            "dropped_entries": 0,
            "signals":         sorted(signals) if signals else [],
            "provenance":      prov,
        }

    ordered = sorted(entries, key=lambda e: e["time"])

    if signals is None:
        watched = sorted({k for e in ordered for k in _flat_signals(e)})
    else:
        watched = sorted(signals)

    kept      = []
    prev_vals = None

    for entry in ordered:
        flat = _flat_signals(entry)

        vals = {}
        for k in watched:
            v = flat.get(k)
            if isinstance(v, float):
                raise TypeError(
                    f"compress_to_transitions is discrete-only: signal "
                    f"{k!r} at t={entry['time']}ms carries a float "
                    f"({v!r}). Analog signals need deadband compression, "
                    f"which is not implemented."
                )
            vals[k] = v

        if prev_vals is None or vals != prev_vals:
            kept.append(dict(entry))
        prev_vals = vals

    # Always preserve the trace's end time.
    if kept[-1]["time"] != ordered[-1]["time"]:
        kept.append(dict(ordered[-1]))

    # held_from / held_until: how long each kept state stood.
    for i, entry in enumerate(kept):
        entry["held_from"] = entry["time"]
        entry["held_until"] = (kept[i + 1]["time"] if i + 1 < len(kept)
                               else ordered[-1]["time"])

    return {
        "entries":         kept,
        "total_entries":   len(ordered),
        "kept_entries":    len(kept),
        "dropped_entries": len(ordered) - len(kept),
        "signals":         watched,
        "provenance":      prov,
    }


# ---------------------------------------------------------------------------
# Offset diagnostics
# ---------------------------------------------------------------------------

# A run of this many consecutive non-zero-offset pairs counts as a
# persistent divergence rather than isolated jitter.
_DIVERGENCE_RUN = 3

# Clamped-offset thresholds. A cascade shifts every pair by the same
# whole sample, so the non-zero offsets are near-constant and single-
# signed; jitter scatters around zero and changes sign.
_CLAMP_MIN_FRACTION = 0.10   # of aligned pairs carrying a non-zero offset
_CLAMP_MIN_PAIRS    = 3
_CLAMP_SAME_SIGN    = 0.90   # fraction sharing one sign
_CLAMP_STDEV_RATIO  = 0.25   # stdev(offsets) / mean(|offsets|)


def offset_histogram(aligned):
    """
    Summarise the offset distribution of aligned pairs, diagnostically.

    The point of this function is that total_aligned lies. An alignment
    that has cascaded — every sim entry paired with the next real
    sample — reports a full match while comparing the wrong pairs. The
    offset distribution is where that shows up.

    Returns:
        {
          "count":                int,    # aligned pairs
          "nonzero_offset_pairs": int,
          "min_ms":   int | None,
          "max_ms":   int | None,
          "mean_ms":  float | None,
          "stdev_ms": float | None,
          "first_divergence_time": int | None,
              # sim time of the first pair starting a run of
              # _DIVERGENCE_RUN consecutive non-zero offsets. On a
              # cascade this IS the dropped sample.
          "cascade_suspected": bool,
              # offsets are CLAMPED (many, same-signed, near-constant)
              # AND begin after the trace started. A clamped offset
              # present from the very first pair is a constant clock
              # skew between the two traces, not a cascade — pairing
              # is still correct, so it is reported through
              # constant_offset_suspected instead.
          "constant_offset_suspected": bool,
        }
    """
    import statistics

    empty = {
        "count": 0, "nonzero_offset_pairs": 0,
        "min_ms": None, "max_ms": None,
        "mean_ms": None, "stdev_ms": None,
        "first_divergence_time": None,
        "cascade_suspected": False,
        "constant_offset_suspected": False,
    }
    if not aligned:
        return empty

    offsets = [p["offset_ms"] for p in aligned]
    nonzero = [o for o in offsets if o != 0]

    # First sustained run of non-zero offsets.
    run_len = min(_DIVERGENCE_RUN, len(aligned))
    first_divergence_time = None
    run = 0
    start_idx = None
    for i, o in enumerate(offsets):
        if o != 0:
            if run == 0:
                start_idx = i
            run += 1
            if run >= run_len:
                first_divergence_time = aligned[start_idx]["time_sim"]
                break
        else:
            run = 0
            start_idx = None

    clamped = False
    if nonzero and (len(nonzero) >= max(_CLAMP_MIN_PAIRS,
                                        _CLAMP_MIN_FRACTION * len(aligned))):
        positives = sum(1 for o in nonzero if o > 0)
        same_sign = max(positives, len(nonzero) - positives) / len(nonzero)
        mean_abs  = statistics.mean(abs(o) for o in nonzero)
        stdev_nz  = statistics.pstdev(nonzero) if len(nonzero) > 1 else 0.0
        clamped = (same_sign >= _CLAMP_SAME_SIGN and
                   mean_abs > 0 and
                   stdev_nz <= _CLAMP_STDEV_RATIO * mean_abs)

    started_clean = (first_divergence_time is not None and
                     first_divergence_time != aligned[0]["time_sim"])

    return {
        "count":                len(aligned),
        "nonzero_offset_pairs": len(nonzero),
        "min_ms":  min(offsets),
        "max_ms":  max(offsets),
        "mean_ms":  round(statistics.mean(offsets), 3),
        "stdev_ms": round(statistics.pstdev(offsets), 3)
                    if len(offsets) > 1 else 0.0,
        "first_divergence_time": first_divergence_time,
        "cascade_suspected":         clamped and started_clean,
        "constant_offset_suspected": clamped and not started_clean,
    }


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------

def resolve_tolerance(tolerance_ms=50, scan_period_ms=None,
                      tolerance_scans=1, sensor_delay_ms=0):
    """
    Resolve an effective alignment tolerance.

    Tolerance must be expressed in scan cycles, not wall-clock guesses.
    A collector's sample and the PLC's scan are not phase-locked, so a
    transition can land anywhere inside one scan period; a tolerance
    tighter than one scan reads every transition as a mismatch.

    Pass tolerance_ms=None to derive it:
        max(1, tolerance_scans) * scan_period_ms + sensor_delay_ms

    An explicit tolerance_ms always wins, so existing callers are
    unaffected.
    """
    if tolerance_ms is not None:
        return tolerance_ms
    if scan_period_ms is None:
        raise ValueError(
            "scan_period_ms is required when tolerance_ms is None"
        )
    return max(1, tolerance_scans) * scan_period_ms + sensor_delay_ms


def align_traces(sim_trace, real_trace, tolerance_ms=50,
                 scan_period_ms=None, tolerance_scans=1,
                 sensor_delay_ms=0):
    """
    Align sim_trace and real_trace entries by time.

    Both traces are sorted by timestamp on ingest. For each sim entry
    in ascending time order, the closest unconsumed real entry within
    ±tolerance is matched; ties go to the earlier real timestamp. Each
    real entry can be consumed at most once.

    STEAL-BACK (k=1 heuristic). Before a sim entry consumes a real
    entry, the next sim entry is checked: if it matches that real
    entry strictly more closely and can still reach it within
    tolerance, the current entry defers and tries its next-best
    candidate. Without this, a single dropped real sample cascades —
    every subsequent sim entry consumes its neighbour's sample, and
    the alignment reports a full match while comparing wrong pairs.

    The lookahead is one entry deep. A cascade that only resolves by
    looking two or more entries ahead is not caught, and neither is
    the general case, which needs optimal min-cost matching. This is
    a cheap guard against the common failure, not a correctness
    guarantee — which is why offset_histogram, not steal-back, is what
    makes a bad alignment visible.

    Args:
        sim_trace       : list | dict — sim entries ("time", "inputs",
                          "outputs") or a wrapped trace
        real_trace      : list | dict — real entries ("time", "signals")
                          or a wrapped trace
        tolerance_ms    : int | None — max allowed offset. None derives
                          it from scan_period_ms (see resolve_tolerance)
        scan_period_ms  : int | None — PLC scan period, for derivation
        tolerance_scans : int — scan cycles of slack, minimum 1
        sensor_delay_ms : int — extra slack for modelled sensor delay

    Returns:
        {
          "aligned":          [...],   # matched pairs
          "unmatched_sim":    [...],   # sim entries with no real match
          "unmatched_real":   [...],   # real entries with no sim match
          "total_sim":        int,
          "total_real":       int,
          "total_aligned":    int,
          "tolerance_ms":     int,
          "duplicate_sim_timestamps":  int,
          "duplicate_real_timestamps": int,
          "provenance_sim":   str,
          "provenance_real":  str,
          "program_sim":      str | None,   # ST program each trace
          "program_real":     str | None,   # declares, if any
          "offsets":          {...},   # offset_histogram() — read this,
                                       # not total_aligned
          "steal_backs":      int,     # deferrals made (see below)
          "warnings":         [str, ...]
        }

    Raises:
        ValueError — if either trace declares TS_ARRIVAL and the
        effective tolerance is 0. Arrival timestamps carry poll phase
        and network jitter; exact alignment against them is never
        correct, and the caller does not get to assert otherwise.

    Complexity:
        O(n log n + m log m) to sort, then a linear sweep. Each sim
        entry scans only the real entries inside its tolerance window,
        so the sweep is O(n + m) whenever the window holds a bounded
        number of samples (tolerance ≈ one scan period). A tolerance
        far wider than the sample period widens the window and the
        sweep degrades toward the old quadratic behaviour.
    """
    sim_entries,  sim_prov  = unwrap_trace(sim_trace)
    real_entries, real_prov = unwrap_trace(real_trace)

    tol = resolve_tolerance(tolerance_ms, scan_period_ms,
                            tolerance_scans, sensor_delay_ms)

    warnings = []

    ts_sim  = sim_prov.get("timestamp",  TS_UNKNOWN)
    ts_real = real_prov.get("timestamp", TS_UNKNOWN)

    if tol == 0:
        arrival_sides = [name for name, ts in (("sim", ts_sim),
                                               ("real", ts_real))
                         if ts == TS_ARRIVAL]
        if arrival_sides:
            raise ValueError(
                f"tolerance 0 is invalid for arrival-timestamped traces "
                f"({', '.join(arrival_sides)}): arrival timestamps carry "
                f"poll phase and network jitter. Derive a tolerance from "
                f"the scan period, or record scan timestamps at source."
            )

    for name, ts in (("sim", ts_sim), ("real", ts_real)):
        if ts == TS_UNKNOWN:
            warnings.append(
                f"{name} trace declares no timestamp provenance; "
                f"assuming {TS_UNKNOWN}"
            )

    # Program identity is provenance, not a lookup key: the same symbol
    # means different things in different ST programs, so comparing
    # traces from two programs compares two different machines.
    prog_sim  = sim_prov.get("program")
    prog_real = real_prov.get("program")
    if prog_sim and prog_real and prog_sim != prog_real:
        warnings.append(
            f"program mismatch: sim trace declares {prog_sim}, real "
            f"trace declares {prog_real}. Symbol meanings differ "
            f"between programs; this comparison is not meaningful."
        )

    dup_sim  = _count_duplicate_timestamps(sim_entries)
    dup_real = _count_duplicate_timestamps(real_entries)
    for name, dupes in (("sim", dup_sim), ("real", dup_real)):
        if dupes:
            warnings.append(
                f"{name} trace has {dupes} duplicate timestamp(s); "
                f"alignment order among them is by input order"
            )

    sim_sorted  = sorted(sim_entries,  key=lambda e: e["time"])
    real_sorted = sorted(real_entries, key=lambda e: e["time"])

    m = len(real_sorted)
    consumed = [False] * m

    aligned       = []
    unmatched_sim = []
    steal_backs   = 0

    lo = 0   # first real index that may still fall in a future window
    hi = 0   # first real index past the current window

    for idx, sim_entry in enumerate(sim_sorted):
        t_sim  = sim_entry["time"]
        t_next = (sim_sorted[idx + 1]["time"]
                  if idx + 1 < len(sim_sorted) else None)

        # Sim time is non-decreasing, so both cursors advance monotonically.
        while hi < m and real_sorted[hi]["time"] <= t_sim + tol:
            hi += 1
        while lo < hi and (real_sorted[lo]["time"] < t_sim - tol
                           or consumed[lo]):
            lo += 1

        candidates = []
        for i in range(lo, hi):
            if consumed[i]:
                continue
            delta = abs(real_sorted[i]["time"] - t_sim)
            if delta <= tol:
                candidates.append((delta, i))
        # (delta, index): closest first, ties to the earlier timestamp.
        candidates.sort()

        chosen = None
        for delta, i in candidates:
            if t_next is not None:
                delta_next = abs(real_sorted[i]["time"] - t_next)
                if delta_next < delta and delta_next <= tol:
                    # The next sim entry matches this real entry more
                    # exactly and can still reach it — leave it alone.
                    steal_backs += 1
                    continue
            chosen = i
            break

        if chosen is not None:
            consumed[chosen] = True
            best_real = real_sorted[chosen]
            aligned.append({
                "time_sim":  t_sim,
                "time_real": best_real["time"],
                "offset_ms": best_real["time"] - t_sim,
                "sim":       sim_entry,
                "real":      best_real
            })
        else:
            unmatched_sim.append(sim_entry)

    unmatched_real = [real_sorted[i] for i in range(m) if not consumed[i]]

    offsets = offset_histogram(aligned)

    if offsets["cascade_suspected"]:
        warnings.append(
            f"cascade suspected: {offsets['nonzero_offset_pairs']} of "
            f"{offsets['count']} pairs carry a clamped offset "
            f"(mean {offsets['mean_ms']}ms, stdev {offsets['stdev_ms']}ms) "
            f"from t={offsets['first_divergence_time']}ms onward. "
            f"total_aligned is not trustworthy: sim entries are likely "
            f"paired with their neighbours' samples."
        )
    elif offsets["constant_offset_suspected"]:
        warnings.append(
            f"constant offset of ~{offsets['mean_ms']}ms between traces "
            f"(pairing is still correct; clocks differ)"
        )

    return {
        "aligned":        aligned,
        "unmatched_sim":  unmatched_sim,
        "unmatched_real": unmatched_real,
        "total_sim":      len(sim_entries),
        "total_real":     len(real_entries),
        "total_aligned":  len(aligned),
        "tolerance_ms":   tol,
        "duplicate_sim_timestamps":  dup_sim,
        "duplicate_real_timestamps": dup_real,
        "provenance_sim":  ts_sim,
        "provenance_real": ts_real,
        "program_sim":     prog_sim,
        "program_real":    prog_real,
        "offsets":         offsets,
        "steal_backs":     steal_backs,
        "warnings":        warnings,
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
    if result.get("duplicate_sim_timestamps") or \
       result.get("duplicate_real_timestamps"):
        print(f"    duplicates    : sim={result['duplicate_sim_timestamps']} "
              f"real={result['duplicate_real_timestamps']}")
    for w in result.get("warnings", []):
        print(f"    [warn] {w}")
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
    import time as _time
    from sim_trace import load_sim_trace
    from real_trace import load_real_trace, create_mock_real_trace

    print("=" * 60)
    print("Phase 7 - Step 6: Trace Alignment Engine")
    print("=" * 60)

    sim_trace_path = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found — run sim_trace.py first")
        exit(1)

    sim_trace = load_sim_trace(sim_trace_path)

    # -------------------------------------------------------
    # Test 1: perfect alignment (same timestamps)
    # -------------------------------------------------------
    print("\nTest 1 — Perfect alignment (identical timestamps):")
    real_trace_exact = create_mock_real_trace(sim_trace)
    result1 = align_traces(sim_trace, real_trace_exact, tolerance_ms=0)
    print_alignment(result1)

    # -------------------------------------------------------
    # Test 2: real trace offset by +25ms
    # -------------------------------------------------------
    print("\nTest 2 — Real trace offset by +25ms (tolerance 50ms):")
    real_trace_offset = [
        {"time": e["time"] + 25, "signals": e["signals"]}
        for e in real_trace_exact
    ]
    result2 = align_traces(sim_trace, real_trace_offset, tolerance_ms=50)
    print_alignment(result2)

    # -------------------------------------------------------
    # Test 3: tolerance too tight
    # -------------------------------------------------------
    print("\nTest 3 — Same offset, tolerance 10ms (too tight):")
    result3 = align_traces(sim_trace, real_trace_offset, tolerance_ms=10)
    print_alignment(result3)

    # -------------------------------------------------------
    # Test 4: missing real entry
    # -------------------------------------------------------
    print("\nTest 4 — Real trace missing t=300ms entry:")
    real_trace_missing = [e for e in real_trace_exact if e["time"] != 300]
    result4 = align_traces(sim_trace, real_trace_missing, tolerance_ms=0)
    print_alignment(result4)

    # -------------------------------------------------------
    # Test 5: tolerance expressed in scan cycles
    # -------------------------------------------------------
    print("\nTest 5 — Tolerance derived from scan period:")
    tol_1scan = resolve_tolerance(None, scan_period_ms=10,
                                  tolerance_scans=1)
    tol_2scan = resolve_tolerance(None, scan_period_ms=10,
                                  tolerance_scans=2, sensor_delay_ms=5)
    tol_floor = resolve_tolerance(None, scan_period_ms=10,
                                  tolerance_scans=0)
    print(f"  1 scan @10ms                    → {tol_1scan}ms")
    print(f"  2 scans @10ms + 5ms sensor delay → {tol_2scan}ms")
    print(f"  0 scans @10ms (floored to 1)     → {tol_floor}ms")

    # -------------------------------------------------------
    # Test 6: timestamp provenance
    # -------------------------------------------------------
    print("\nTest 6 — Timestamp provenance:")
    wrapped_scan = wrap_trace(real_trace_exact, TS_SCAN, device="shim")
    wrapped_arr  = wrap_trace(real_trace_exact, TS_ARRIVAL,
                              device="collector")

    res_scan = align_traces(sim_trace, wrapped_scan, tolerance_ms=0)
    print(f"  scan-timestamped, tolerance 0 → "
          f"{res_scan['total_aligned']} aligned, "
          f"provenance_real={res_scan['provenance_real']}")

    refused = None
    try:
        align_traces(sim_trace, wrapped_arr, tolerance_ms=0)
    except ValueError as exc:
        refused = str(exc)
    print(f"  arrival-timestamped, tolerance 0 → refused")

    res_arr = align_traces(sim_trace, wrapped_arr, tolerance_ms=None,
                           scan_period_ms=10, tolerance_scans=1)
    print(f"  arrival-timestamped, 1 scan @10ms → "
          f"{res_arr['total_aligned']} aligned "
          f"(tolerance {res_arr['tolerance_ms']}ms)")

    bare = align_traces(sim_trace, real_trace_exact, tolerance_ms=0)
    print(f"  bare list → warnings: {len(bare['warnings'])}")

    # -------------------------------------------------------
    # Test 7: duplicate timestamps degrade quietly
    # -------------------------------------------------------
    print("\nTest 7 — Duplicate timestamps:")
    real_dupes = real_trace_exact + [dict(real_trace_exact[2])]
    res_dupes  = align_traces(sim_trace, real_dupes, tolerance_ms=0)
    print(f"  duplicate_real_timestamps: "
          f"{res_dupes['duplicate_real_timestamps']}")
    print(f"  aligned: {res_dupes['total_aligned']}, "
          f"unmatched_real: {len(res_dupes['unmatched_real'])}")

    # -------------------------------------------------------
    # Test 8: transition compression
    # -------------------------------------------------------
    print("\nTest 8 — compress_to_transitions:")
    compressed = compress_to_transitions(sim_trace)
    print(f"  {compressed['total_entries']} entries → "
          f"{compressed['kept_entries']} transitions "
          f"({compressed['dropped_entries']} dropped)")
    print(f"  watched signals: {compressed['signals']}")
    for e in compressed["entries"]:
        print(f"    t={e['time']:>5}ms  held {e['held_from']}→"
              f"{e['held_until']}ms  "
              f"inputs={e['inputs']} outputs={e['outputs']}")

    print("\n  Explicit signal set (streaming, Y0 only):")
    compressed_y0 = compress_to_transitions(sim_trace, signals=["Y0"])
    print(f"    {compressed_y0['total_entries']} → "
          f"{compressed_y0['kept_entries']} transitions "
          f"at t={[e['time'] for e in compressed_y0['entries']]}")

    print("\n  Float signal rejection:")
    float_trace = [
        {"time": 0,   "signals": {"melt_pressure": 101.4}},
        {"time": 100, "signals": {"melt_pressure": 101.7}},
    ]
    float_err = None
    try:
        compress_to_transitions(float_trace)
    except TypeError as exc:
        float_err = str(exc)
    print(f"    rejected: {float_err.splitlines()[0][:70]}...")

    # -------------------------------------------------------
    # Test 9: cascade regression — one dropped sample must not
    # re-pair the rest of the trace, and must never be reported
    # as a clean alignment.
    # -------------------------------------------------------
    print("\nTest 9 — Cascade regression (1 sample dropped of 1000):")

    CASCADE_N      = 1000
    CASCADE_PERIOD = 10
    CASCADE_DROP   = 500

    casc_sim = [{"time": i * CASCADE_PERIOD,
                 "inputs": {"X0": False}, "outputs": {"Y0": False}}
                for i in range(CASCADE_N)]
    casc_real = [{"time": i * CASCADE_PERIOD,
                  "signals": {"X0": False, "Y0": False}}
                 for i in range(CASCADE_N) if i != CASCADE_DROP]

    casc = align_traces(casc_sim, casc_real,
                        tolerance_ms=None, scan_period_ms=CASCADE_PERIOD,
                        tolerance_scans=1)
    casc_off = casc["offsets"]
    print(f"  aligned={casc['total_aligned']}/{CASCADE_N}  "
          f"unmatched_sim={len(casc['unmatched_sim'])}  "
          f"steal_backs={casc['steal_backs']}")
    print(f"  nonzero_offset_pairs={casc_off['nonzero_offset_pairs']}  "
          f"min={casc_off['min_ms']} max={casc_off['max_ms']} "
          f"mean={casc_off['mean_ms']} stdev={casc_off['stdev_ms']}")
    print(f"  first_divergence_time={casc_off['first_divergence_time']}  "
          f"cascade_suspected={casc_off['cascade_suspected']}")

    # Steal-back prevents the dropped-sample cascade, but not every
    # clamped offset — a collector that resyncs its clock mid-trace
    # shifts every later pair by a constant sub-period amount, with no
    # closer partner for steal-back to defer to. That is the residual
    # case the histogram exists to catch.
    print("\n  Clamped offset step (clock resync mid-trace):")
    STEP_AT, STEP_MS = 5000, 4
    partial_real = [
        {"time": e["time"] + (STEP_MS if e["time"] >= STEP_AT else 0),
         "signals": e["signals"]}
        for e in casc_real
    ]
    casc2 = align_traces(casc_sim, partial_real,
                         tolerance_ms=CASCADE_PERIOD)
    casc2_off = casc2["offsets"]
    print(f"    aligned={casc2['total_aligned']}  "
          f"nonzero={casc2_off['nonzero_offset_pairs']}  "
          f"stdev={casc2_off['stdev_ms']}  "
          f"first_divergence_time={casc2_off['first_divergence_time']}  "
          f"cascade_suspected={casc2_off['cascade_suspected']}")
    for w in casc2["warnings"]:
        print(f"    [warn] {w}")

    # Scattered jitter must NOT trip the detector.
    print("\n  Scattered jitter (must not be flagged):")
    jitter_real = [{"time": e["time"] + (2 if i % 3 == 0 else
                                         -2 if i % 3 == 1 else 0),
                    "signals": e["signals"]}
                   for i, e in enumerate(casc_real)]
    jit = align_traces(casc_sim, jitter_real, tolerance_ms=CASCADE_PERIOD)
    jit_off = jit["offsets"]
    print(f"    nonzero={jit_off['nonzero_offset_pairs']}  "
          f"mean={jit_off['mean_ms']} stdev={jit_off['stdev_ms']}  "
          f"cascade_suspected={jit_off['cascade_suspected']}")

    # A constant skew is a clock difference, not a cascade.
    print("\n  Constant skew (reported separately, not as cascade):")
    skew_off = result2["offsets"]
    print(f"    nonzero={skew_off['nonzero_offset_pairs']}  "
          f"mean={skew_off['mean_ms']}  "
          f"cascade_suspected={skew_off['cascade_suspected']}  "
          f"constant_offset_suspected="
          f"{skew_off['constant_offset_suspected']}")

    # -------------------------------------------------------
    # Test 10: linear scaling
    # -------------------------------------------------------
    print("\nTest 10 — Scaling (100k entries per side):")
    N = 100_000
    big_sim  = [{"time": t * 10,
                 "inputs": {"X0": False}, "outputs": {"Y0": False}}
                for t in range(N)]
    big_real = [{"time": t * 10 + 2, "signals": {"X0": False, "Y0": False}}
                for t in range(N)]

    t0 = _time.perf_counter()
    big_res = align_traces(big_sim, big_real, tolerance_ms=10)
    elapsed = _time.perf_counter() - t0
    print(f"  aligned {big_res['total_aligned']}/{N} in {elapsed:.2f}s")
    print(f"  (legacy would need ~{N * N / 1e9:.0f}e9 comparisons)")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert result1["total_aligned"]    == 7, "perfect: all 7 aligned"
    assert len(result1["unmatched_sim"])  == 0
    assert len(result1["unmatched_real"]) == 0
    print("  PASS — Test 1: perfect alignment, 7/7 matched")

    assert result2["total_aligned"]    == 7, "offset: all 7 aligned"
    for pair in result2["aligned"]:
        assert pair["offset_ms"] == 25, "all offsets must be +25ms"
    print("  PASS — Test 2: offset alignment, all offsets = +25ms")

    assert result3["total_aligned"]    == 0, "tight: 0 aligned"
    assert len(result3["unmatched_sim"]) == 7
    print("  PASS — Test 3: tight tolerance, 0/7 matched")

    assert result4["total_aligned"]    == 6, "missing: 6 aligned"
    assert len(result4["unmatched_sim"]) == 1
    assert result4["unmatched_sim"][0]["time"] == 300
    print("  PASS — Test 4: missing entry, t=300ms unmatched")

    assert tol_1scan == 10,  "1 scan @10ms = 10ms"
    assert tol_2scan == 25,  "2 scans @10ms + 5ms delay = 25ms"
    assert tol_floor == 10,  "tolerance_scans floors at 1"
    try:
        resolve_tolerance(None, scan_period_ms=None)
        raise AssertionError("must require scan_period_ms")
    except ValueError:
        pass
    print("  PASS — Test 5: tolerance derives from scan cycles")

    assert res_scan["provenance_real"] == TS_SCAN
    assert res_scan["total_aligned"]   == 7, "scan timestamps align exactly"
    assert refused is not None, "tolerance 0 on arrival must raise"
    assert "arrival" in refused
    assert res_arr["tolerance_ms"] == 10
    assert res_arr["total_aligned"] == 7
    assert any(TS_UNKNOWN in w for w in bare["warnings"]), \
        "bare list must warn about unknown provenance"
    assert bare["total_aligned"] == 7, "bare list still aligns (permissive)"
    print("  PASS — Test 6: provenance refused tolerance 0 on arrival, "
          "warned on unknown, allowed on scan")

    assert res_dupes["duplicate_real_timestamps"] == 1
    assert len(res_dupes["warnings"]) >= 1, "duplicates must warn"
    print("  PASS — Test 7: duplicates counted and warned, never raised")

    assert compressed["total_entries"] == 7
    assert compressed["kept_entries"] < compressed["total_entries"], \
        "compression must drop steady-state ticks"
    assert compressed["entries"][0]["time"] == sim_trace[0]["time"], \
        "first entry always kept"
    assert compressed["entries"][-1]["time"] == sim_trace[-1]["time"], \
        "last entry always kept (preserves trace end time)"
    for i, e in enumerate(compressed["entries"][:-1]):
        assert e["held_until"] == compressed["entries"][i + 1]["held_from"]
    print(f"  PASS — Test 8: {compressed['total_entries']} ticks → "
          f"{compressed['kept_entries']} transitions, first/last kept")

    # Round-trip: expanding the compressed trace reproduces every
    # original tick's signal values.
    def _expand(compressed_result, original):
        out = []
        kept = compressed_result["entries"]
        for entry in original:
            t = entry["time"]
            state = None
            for k in kept:
                if k["time"] <= t:
                    state = k
                else:
                    break
            out.append((t, _flat_signals(state)))
        return out

    for t, vals in _expand(compressed, sim_trace):
        original = next(e for e in sim_trace if e["time"] == t)
        assert vals == _flat_signals(original), \
            f"round-trip mismatch at t={t}ms"
    print("  PASS — Test 8: compress→expand identical at every "
          "original timestamp")

    assert float_err is not None, "float signals must be rejected"
    assert "discrete-only" in float_err
    print("  PASS — Test 8: float signals rejected (analog needs deadband)")

    # Steal-back must stop the cascade at its origin: the sim entry
    # whose sample vanished goes unmatched, and every later entry
    # keeps its own sample. Bound is the steal-back window, not n/2.
    assert casc_off["nonzero_offset_pairs"] <= 1, \
        (f"cascade not contained: {casc_off['nonzero_offset_pairs']} "
         f"pairs carry a non-zero offset (unguarded greedy gives ~n/2)")
    assert len(casc["unmatched_sim"]) == 1, \
        "the sim entry whose sample was dropped must be unmatched"
    assert casc["unmatched_sim"][0]["time"] == CASCADE_DROP * CASCADE_PERIOD
    assert casc_off["cascade_suspected"] is False, \
        "a contained drop is not a cascade"
    print(f"  PASS — Test 9: dropped sample contained — "
          f"{casc_off['nonzero_offset_pairs']} shifted pair(s), "
          f"1 unmatched at t={CASCADE_DROP * CASCADE_PERIOD}ms "
          f"(unguarded greedy shifts ~{CASCADE_N // 2})")

    # When a clamped cascade does occur, it must be detected and must
    # not be reportable as clean.
    assert casc2_off["cascade_suspected"] is True, \
        "clamped whole-sample shift must be detected"
    assert casc2_off["first_divergence_time"] is not None
    assert any("cascade suspected" in w for w in casc2["warnings"]), \
        "a suspected cascade must warn"
    print(f"  PASS — Test 9: clamped cascade detected at "
          f"t={casc2_off['first_divergence_time']}ms and warned")

    assert jit_off["nonzero_offset_pairs"] > 0, "jitter present"
    assert jit_off["cascade_suspected"] is False, \
        "scattered jitter must not be flagged (benign on arrival path)"
    print(f"  PASS — Test 9: scattered jitter "
          f"({jit_off['nonzero_offset_pairs']} pairs, "
          f"stdev {jit_off['stdev_ms']}ms) not flagged")

    assert skew_off["cascade_suspected"] is False
    assert skew_off["constant_offset_suspected"] is True, \
        "constant skew reported separately from cascade"
    print("  PASS — Test 9: constant skew reported as skew, not cascade")

    assert big_res["total_aligned"] == N, "all 100k aligned"
    assert elapsed < 30.0, f"scaling: took {elapsed:.1f}s"
    print(f"  PASS — Test 10: 100k×100k aligned in {elapsed:.2f}s "
          f"(quadratic scan would not finish)")
