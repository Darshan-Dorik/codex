"""
trace_diff.py — Trace Diff Engine

Compares aligned sim and real trace pairs, detecting mismatches
between expected (sim) and actual (real) values.

Two modes:

  mode="ticks" (default) — compare every aligned tick, signal by
  signal. Mismatch format:
    {
      "time":   int,    # sim time of the mismatch
      "signal": str,    # signal name (e.g. "Y0")
      "sim":    bool,   # value in simulation
      "real":   bool    # value in real trace
    }

  mode="transitions" — compress both traces to state changes, then
  align and compare per-signal EDGES. Intended for long runs, where
  per-tick diffing is both unaffordable and unreadable: a 7-day soak
  at a 10ms scan is ~60M ticks but only a few thousand transitions.
  Mismatch format:
    {
      "signal":       str,
      "kind":         "value" | "missing_real" | "missing_sim",
      "time":         int,        # sim edge time, or real time if
                                  # the edge exists only on the real side
      "sim_edge_ms":  int | None,
      "real_edge_ms": int | None,
      "delta_ms":     int | None, # real_edge - sim_edge
      "sim":          value | None,
      "real":         value | None
    }

  Transitions mode is DISCRETE-ONLY — it inherits that restriction
  from compress_to_transitions, which rejects float signals.

CASCADE GATE
------------
In transitions mode, a suspected cascade (or any clamped offset
step) makes the whole comparison untrustworthy: sim edges are being
matched against their neighbours' samples, so a single dropped poll
produces a confident-looking mismatch at every subsequent edge. When
that is detected the result carries trustworthy=False and a loud
warning, and print_diff refuses to report "no mismatches detected"
even when the mismatch list is empty. It never raises — a degraded
report is still useful, a crashed one is not.
"""

from trace_aligner import (align_traces, compress_to_transitions,
                           offset_histogram, resolve_tolerance,
                           _flat_signals)


def _sim_signals(entry):
    """Flat signal view of a sim entry (inputs + outputs)."""
    sim_signals = {}
    sim_signals.update(entry.get("inputs", {}))
    sim_signals.update(entry.get("outputs", {}))
    return sim_signals


def diff_traces(sim_trace, real_trace, tolerance_ms=50,
                signals_to_check=None, mode="ticks",
                scan_period_ms=None, tolerance_scans=1,
                sensor_delay_ms=0):
    """
    Align and diff two traces, returning all signal mismatches.

    Args:
        sim_trace        : list | dict — simulation trace
        real_trace       : list | dict — real trace
        tolerance_ms     : int | None — alignment tolerance. None
                           derives it from scan_period_ms.
        signals_to_check : list | None — specific signals to compare;
                           if None, compares all signals present in sim
        mode             : "ticks" | "transitions"
        scan_period_ms   : int | None — for deriving tolerance
        tolerance_scans  : int — scan cycles of slack, minimum 1
        sensor_delay_ms  : int — extra slack for modelled sensor delay

    Returns:
        ticks mode:
        {
          "mode":             "ticks",
          "mismatches":       [...],
          "alignment":        {...},
          "total_compared":   int,
          "total_mismatches": int,
          "warnings":         [str, ...],
          "trustworthy":      bool
        }

        transitions mode: as above, plus "per_signal" (one alignment
        per signal), "compression" (sim/real compression stats) and
        "cascade_suspected".
    """
    if mode not in ("ticks", "transitions"):
        raise ValueError(
            f"unknown mode {mode!r} (expected 'ticks' or 'transitions')"
        )

    if mode == "ticks":
        return _diff_ticks(sim_trace, real_trace, tolerance_ms,
                           signals_to_check, scan_period_ms,
                           tolerance_scans, sensor_delay_ms)
    return _diff_transitions(sim_trace, real_trace, tolerance_ms,
                             signals_to_check, scan_period_ms,
                             tolerance_scans, sensor_delay_ms)


def _diff_ticks(sim_trace, real_trace, tolerance_ms, signals_to_check,
                scan_period_ms, tolerance_scans, sensor_delay_ms):
    """Per-tick comparison across aligned pairs."""
    alignment = align_traces(sim_trace, real_trace, tolerance_ms,
                             scan_period_ms, tolerance_scans,
                             sensor_delay_ms)
    mismatches = []
    total_compared = 0

    for pair in alignment["aligned"]:
        t_sim      = pair["time_sim"]
        sim_entry  = pair["sim"]
        real_entry = pair["real"]

        sim_signals  = _sim_signals(sim_entry)
        real_signals = real_entry.get("signals", {})

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

    warnings = list(alignment["warnings"])
    cascade  = alignment["offsets"]["cascade_suspected"]

    return {
        "mode":             "ticks",
        "mismatches":       mismatches,
        "alignment":        alignment,
        "program":          alignment["program_sim"] or
                            alignment["program_real"],
        "total_compared":   total_compared,
        "total_mismatches": len(mismatches),
        "warnings":         warnings,
        "trustworthy":      not cascade,
    }


def _signal_edges(entries, signal):
    """
    Extract the edge list for one signal from compressed entries.

    The first entry is always emitted, so a differing INITIAL state is
    caught rather than silently accepted as "no edge".
    """
    edges = []
    prev  = _MISSING
    for entry in entries:
        value = _flat_signals(entry).get(signal)
        if prev is _MISSING or value != prev:
            edges.append({"time": entry["time"],
                          "signals": {signal: value}})
        prev = value
    return edges


_MISSING = object()


def _diff_transitions(sim_trace, real_trace, tolerance_ms,
                      signals_to_check, scan_period_ms,
                      tolerance_scans, sensor_delay_ms):
    """Per-signal edge comparison over compressed traces."""
    tol = resolve_tolerance(tolerance_ms, scan_period_ms,
                            tolerance_scans, sensor_delay_ms)

    sim_c  = compress_to_transitions(sim_trace, signals=signals_to_check)
    real_c = compress_to_transitions(real_trace, signals=signals_to_check)

    if signals_to_check:
        signals = sorted(signals_to_check)
    else:
        # Only signals present on both sides can be compared, matching
        # ticks mode, which skips a key absent from either side.
        signals = sorted(set(sim_c["signals"]) & set(real_c["signals"]))

    mismatches     = []
    per_signal     = {}
    pooled_aligned = []
    total_compared = 0
    warnings       = []

    for sig in signals:
        sim_edges  = _signal_edges(sim_c["entries"], sig)
        real_edges = _signal_edges(real_c["entries"], sig)

        alignment = align_traces(sim_edges, real_edges, tolerance_ms=tol)
        per_signal[sig] = alignment
        pooled_aligned.extend(alignment["aligned"])

        for pair in alignment["aligned"]:
            total_compared += 1
            sim_val  = pair["sim"]["signals"].get(sig)
            real_val = pair["real"]["signals"].get(sig)
            if sim_val != real_val:
                mismatches.append({
                    "signal":       sig,
                    "kind":         "value",
                    "time":         pair["time_sim"],
                    "sim_edge_ms":  pair["time_sim"],
                    "real_edge_ms": pair["time_real"],
                    "delta_ms":     pair["offset_ms"],
                    "sim":          sim_val,
                    "real":         real_val,
                })

        for entry in alignment["unmatched_sim"]:
            mismatches.append({
                "signal":       sig,
                "kind":         "missing_real",
                "time":         entry["time"],
                "sim_edge_ms":  entry["time"],
                "real_edge_ms": None,
                "delta_ms":     None,
                "sim":          entry["signals"].get(sig),
                "real":         None,
            })

        for entry in alignment["unmatched_real"]:
            mismatches.append({
                "signal":       sig,
                "kind":         "missing_sim",
                "time":         entry["time"],
                "sim_edge_ms":  None,
                "real_edge_ms": entry["time"],
                "delta_ms":     None,
                "sim":          None,
                "real":         entry["signals"].get(sig),
            })

    mismatches.sort(key=lambda m: (m["time"], m["signal"], m["kind"]))

    # Pool every aligned edge across signals for the offset statistics —
    # a per-signal edge list is usually too sparse for the clamp test to
    # have anything to work with.
    pooled_aligned.sort(key=lambda p: p["time_sim"])
    pooled_offsets = offset_histogram(pooled_aligned)
    cascade = pooled_offsets["cascade_suspected"]

    for sig, alignment in per_signal.items():
        for w in alignment["warnings"]:
            if "provenance" in w or "duplicate" in w:
                continue   # reported once below, not once per signal
            warnings.append(f"[{sig}] {w}")

    for side, compressed in (("sim", sim_c), ("real", real_c)):
        prov = compressed["provenance"].get("timestamp")
        if prov == "unknown":
            warnings.append(
                f"{side} trace declares no timestamp provenance; "
                f"assuming unknown"
            )

    prog_sim  = sim_c["provenance"].get("program")
    prog_real = real_c["provenance"].get("program")
    if prog_sim and prog_real and prog_sim != prog_real:
        warnings.append(
            f"program mismatch: sim trace declares {prog_sim}, real "
            f"trace declares {prog_real}. Symbol meanings differ "
            f"between programs; this comparison is not meaningful."
        )

    if cascade:
        warnings.insert(0,
            f"CASCADE SUSPECTED — {pooled_offsets['nonzero_offset_pairs']} "
            f"of {pooled_offsets['count']} aligned edges carry a clamped "
            f"offset (mean {pooled_offsets['mean_ms']}ms, stdev "
            f"{pooled_offsets['stdev_ms']}ms) from "
            f"t={pooled_offsets['first_divergence_time']}ms onward. "
            f"Edges are likely matched against neighbouring samples; "
            f"treat every result below as unverified."
        )

    return {
        "mode":             "transitions",
        "mismatches":       mismatches,
        "alignment": {
            "total_sim":     sum(a["total_sim"] for a in per_signal.values()),
            "total_real":    sum(a["total_real"] for a in per_signal.values()),
            "total_aligned": len(pooled_aligned),
            "tolerance_ms":  tol,
            "offsets":       pooled_offsets,
        },
        "per_signal":       per_signal,
        "program":          prog_sim or prog_real,
        "compression": {
            "sim":  {k: sim_c[k] for k in
                     ("total_entries", "kept_entries", "dropped_entries")},
            "real": {k: real_c[k] for k in
                     ("total_entries", "kept_entries", "dropped_entries")},
        },
        "signals":          signals,
        "total_compared":   total_compared,
        "total_mismatches": len(mismatches),
        "cascade_suspected": cascade,
        "warnings":         warnings,
        "trustworthy":      not cascade,
    }


def print_diff(diff_result):
    """Print diff results in a readable format."""
    mode = diff_result.get("mode", "ticks")
    a    = diff_result["alignment"]

    print(f"  Aligned pairs   : {a['total_aligned']} / {a['total_sim']}")
    print(f"  Total compared  : {diff_result['total_compared']} "
          f"{'edge' if mode == 'transitions' else 'signal'} checks")
    print(f"  Total mismatches: {diff_result['total_mismatches']}")

    if mode == "transitions":
        c = diff_result["compression"]
        print(f"  Compression     : sim {c['sim']['total_entries']}→"
              f"{c['sim']['kept_entries']}, "
              f"real {c['real']['total_entries']}→"
              f"{c['real']['kept_entries']}")

    for w in diff_result.get("warnings", []):
        print(f"  [warn] {w}")

    if diff_result["mismatches"]:
        print()
        if mode == "transitions":
            print(f"  {'Signal':10}  {'Kind':13}  {'SimEdge':>9}  "
                  f"{'RealEdge':>9}  {'Delta':>7}  Sim→Real")
            print("  " + "-" * 68)
            for m in diff_result["mismatches"]:
                se = f"{m['sim_edge_ms']}ms" if m["sim_edge_ms"] is not None else "-"
                re_ = f"{m['real_edge_ms']}ms" if m["real_edge_ms"] is not None else "-"
                d  = f"{m['delta_ms']:+d}ms" if m["delta_ms"] is not None else "-"
                print(f"  {m['signal']:10}  {m['kind']:13}  {se:>9}  "
                      f"{re_:>9}  {d:>7}  {m['sim']}→{m['real']}")
        else:
            print(f"  {'Time':>8}  {'Signal':10}  {'Sim':>6}  {'Real':>6}")
            print("  " + "-" * 38)
            for m in diff_result["mismatches"]:
                print(f"  {m['time']:>7}ms  {m['signal']:10}  "
                      f"{str(m['sim']):>6}  {str(m['real']):>6}")
    elif diff_result.get("trustworthy", True):
        print("  No mismatches detected.")
    else:
        # The gate: an untrustworthy alignment never reports clean.
        print("  NO MISMATCHES FOUND, BUT THE ALIGNMENT IS NOT "
              "TRUSTWORTHY — see warnings above.")


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
    # Test 5: transitions mode — clean traces
    # -------------------------------------------------------
    print("\nTest 5 — Transitions mode, identical traces:")
    tdiff1 = diff_traces(sim_trace, real_clean, tolerance_ms=0,
                         mode="transitions")
    print_diff(tdiff1)

    # -------------------------------------------------------
    # Test 6: transitions mode — a single-tick flip is TWO edges
    # -------------------------------------------------------
    print("\nTest 6 — Transitions mode, Y0 flipped at t=300ms:")
    tdiff2 = diff_traces(sim_trace, real_y0_flip, tolerance_ms=0,
                         mode="transitions")
    print_diff(tdiff2)
    print("  (a one-tick flip is two extra real edges — it is a "
          "different question than ticks mode asks)")

    # -------------------------------------------------------
    # Test 7: transitions mode — a shifted edge
    # -------------------------------------------------------
    print("\nTest 7 — Transitions mode, Y0 rises late:")

    def _defer_rise(by_ticks):
        """Push the Y0 rising edge later by N ticks of 100ms."""
        out = []
        for e in create_mock_real_trace(sim_trace):
            sigs = dict(e["signals"])
            if 200 <= e["time"] < 200 + by_ticks * 100:
                sigs["Y0"] = False
            out.append({"time": e["time"], "signals": sigs})
        return out

    # One scan late, with one scan of tolerance: inside tolerance, so it
    # is an OFFSET, not a mismatch. The lateness is still visible.
    tdiff3 = diff_traces(sim_trace, _defer_rise(1), tolerance_ms=None,
                         scan_period_ms=100, tolerance_scans=1,
                         mode="transitions")
    print_diff(tdiff3)
    y0_offsets = [p["offset_ms"] for p in tdiff3["per_signal"]["Y0"]["aligned"]]
    print(f"  Y0 edge offsets: {y0_offsets} "
          f"(late but within tolerance → offset, not mismatch)")

    # Two scans late: beyond tolerance, so the edge genuinely fails to
    # match on either side.
    print("\n  Two scans late (beyond tolerance):")
    tdiff3b = diff_traces(sim_trace, _defer_rise(2), tolerance_ms=None,
                          scan_period_ms=100, tolerance_scans=1,
                          mode="transitions")
    print_diff(tdiff3b)

    # -------------------------------------------------------
    # Test 8: the cascade gate — clean mismatch list, untrusted
    # -------------------------------------------------------
    print("\nTest 8 — Cascade gate (clamped offset step mid-trace):")
    N, PERIOD, STEP_AT, STEP_MS = 400, 10, 2000, 4
    casc_sim = [{"time": i * PERIOD,
                 "inputs": {"X0": bool((i // 20) % 2)},
                 "outputs": {"Y0": bool((i // 20) % 2)}}
                for i in range(N)]
    casc_real = [{"time": i * PERIOD + (STEP_MS if i * PERIOD >= STEP_AT
                                        else 0),
                  "signals": {"X0": bool((i // 20) % 2),
                              "Y0": bool((i // 20) % 2)}}
                 for i in range(N)]
    tdiff4 = diff_traces(casc_sim, casc_real, tolerance_ms=PERIOD,
                         mode="transitions")
    print_diff(tdiff4)

    # -------------------------------------------------------
    # Test 9: invalid mode
    # -------------------------------------------------------
    print("\nTest 9 — Invalid mode rejected:")
    mode_err = None
    try:
        diff_traces(sim_trace, real_clean, mode="edges")
    except ValueError as exc:
        mode_err = str(exc)
    print(f"  {mode_err}")

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

    assert diff1["mode"] == "ticks", "default mode is ticks"
    assert diff1["trustworthy"] is True
    print("  PASS — ticks mode unchanged, tagged mode='ticks'")

    assert tdiff1["mode"] == "transitions"
    assert tdiff1["total_mismatches"] == 0, \
        "identical traces have identical transitions"
    assert tdiff1["compression"]["sim"]["kept_entries"] < \
        tdiff1["compression"]["sim"]["total_entries"], "compression happened"
    assert tdiff1["trustworthy"] is True
    print(f"  PASS — Test 5: transitions mode clean "
          f"({tdiff1['compression']['sim']['total_entries']}→"
          f"{tdiff1['compression']['sim']['kept_entries']} entries, "
          f"{tdiff1['total_compared']} edge checks)")

    assert tdiff2["total_mismatches"] > 0, \
        "a one-tick flip introduces real-side edges"
    assert any(m["kind"] == "missing_sim" for m in tdiff2["mismatches"]), \
        "the spurious edges appear as missing_sim"
    print(f"  PASS — Test 6: one-tick flip surfaces as "
          f"{tdiff2['total_mismatches']} edge event(s)")

    # An edge that is late but inside tolerance is an offset, not a
    # mismatch — that is the whole point of expressing tolerance in
    # scan cycles. It must still be visible in the offsets.
    assert 100 in y0_offsets, \
        "a one-scan-late edge must be recorded as a +100ms offset"
    assert not [m for m in tdiff3["mismatches"] if m["signal"] == "Y0"], \
        "an edge inside tolerance must not be reported as a mismatch"
    print(f"  PASS — Test 7: one-scan-late Y0 rise → offset "
          f"{y0_offsets}, no mismatch")

    late_kinds = {m["kind"] for m in tdiff3b["mismatches"]
                  if m["signal"] == "Y0"}
    assert "missing_real" in late_kinds and "missing_sim" in late_kinds, \
        "an edge beyond tolerance must fail to match on both sides"
    print(f"  PASS — Test 7: two-scans-late Y0 rise → {sorted(late_kinds)}")

    assert tdiff4["cascade_suspected"] is True, "clamped step detected"
    assert tdiff4["trustworthy"] is False, "cascade makes result untrusted"
    assert any("CASCADE SUSPECTED" in w for w in tdiff4["warnings"])
    assert tdiff4["warnings"][0].startswith("CASCADE SUSPECTED"), \
        "the cascade warning must lead"
    print(f"  PASS — Test 8: cascade gate — "
          f"{tdiff4['total_mismatches']} mismatches but "
          f"trustworthy={tdiff4['trustworthy']}")

    assert mode_err is not None and "unknown mode" in mode_err
    print("  PASS — Test 9: invalid mode rejected")
