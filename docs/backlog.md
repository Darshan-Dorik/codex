# Backlog

Deferred work with the reasoning preserved. The derivations here are
the expensive part — redoing them from scratch costs more than the
change itself.

---

## Re-speed the twin to a real loom rate (deferred from the scan-period split)

**Status:** deferred, 2026-08-13. Not blocking any current phase.

**Context.** Splitting `step_ms` into `sim_step_ms` (physics) and
`scan_period_ms` (PLC scan) raised a second, larger question: the twin
does not run at a real loom's speed, and never did.

**The numbers as they stand.** Position-sensor pulse width is
`window / speed`, where `window = 20` position units and
`cycle_length = 360`:

| Profile      | speed (u/s) | cycle time | rpm  | pulse width | samples @100ms |
| ------------ | ----------- | ---------- | ---- | ----------- | -------------- |
| `default`    | 100         | 3.6 s      | 16.7 | 200 ms      | 2              |
| `fast`       | 200         | 1.8 s      | 33.3 | **100 ms**  | **1**          |
| `slow`       | 80          | 4.5 s      | 13.3 | 250 ms      | 2.5            |
| `api_server` | 60          | 6.0 s      | 10.0 | 333 ms      | 3.3            |

At the `fast` profile the pulse is exactly one sample wide, so whether
it is seen depends on sampling phase. That aliasing is resolved by
`scan_period_ms = 10`; it is not why this item exists.

**Why this item exists.** A real 6-shuttle circular loom runs at
~200 rpm. The twin models one position sensor firing once per
revolution, at 10–33 rpm — roughly an order of magnitude slow, with no
per-shuttle event at all.

**The derivation, if this is picked up:**

```
200 rpm                      → 300 ms per revolution
20-unit window of 360 units  → 20/360 × 300 ms = 16.7 ms pulse
16.7 ms pulse @ 10 ms scan   → 1.7 samples — still aliased
                             → forces scan_period_ms = 5
6 shuttles at 200 rpm        → a shuttle passes every ~50 ms
```

So re-speeding is **not** a one-line profile edit. It forces
`scan_period_ms = 5` and a rethink of the sensor window, and the twin
would need per-shuttle events to model a 6-shuttle machine at all.

**Blast radius.** All three calibration profiles in
`outputs/profiles/`, whatever real-world targets `calibration.py`
compares against, and every golden trace. Wider than the golden
re-baseline that the scan-period split already requires — which is why
it was separated from it rather than bundled in.

---

## Deadband compression for analog signals

**Status:** named, not implemented. Blocks transition-mode diffing in
the platform repo.

`trace_aligner.compress_to_transitions` is discrete-only and rejects
float values outright, because exact-equality compression is a silent
no-op on analog data — nothing ever repeats, so every sample is kept
and the function appears to work while doing nothing.

The platform repo's signals are largely analog (melt pressure, motor
load, specific energy), so `mode="transitions"` is unusable there until
a `compress_analog_deadband(trace, deadband, max_gap_ms)` exists: keep
a sample when it moves more than ±deadband from the last kept value,
plus a max-gap heartbeat so a flat signal still produces periodic
anchors.

---

## Optimal trace matching

**Status:** deliberately not done. `align_traces` uses greedy matching
with a k=1 steal-back heuristic.

Steal-back stops the common cascade (one dropped sample re-pairing the
rest of the trace) by deferring a real entry when the next sim entry
matches it strictly more closely. It is one entry deep. A cascade that
only resolves by looking two or more entries ahead is not caught.

The general fix is optimal min-cost bipartite matching, which is
O(n³)-ish and unjustified here. `offset_histogram` is the actual
safety net: it reports `cascade_suspected` when offsets are clamped, so
a mis-paired alignment is visible rather than silent. Revisit only if
the histogram starts flagging cascades that steal-back should have
prevented.
