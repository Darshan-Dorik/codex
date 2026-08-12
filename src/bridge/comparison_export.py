"""
comparison_export.py — Export Comparison Package

Combines sim trace, real trace, diff, and summary into a single
structured JSON package and saves it to disk.

Package schema:
{
  "program":    str,
  "io_map":     {...},
  "sim_trace":  [...],
  "real_trace": [...],
  "diff":       [...],   # raw mismatch list
  "summary": {
    "total_compared":      int,
    "total_mismatches":    int,
    "mismatch_rate":       float,
    "first_mismatch_time": int | None,
    "last_mismatch_time":  int | None,
    "signals":             {...}
  },
  "readable_report": {
    "messages":       [...],
    "summary":        str,
    "has_mismatches": bool
  },
  "offsets":     {...},        # trace_aligner.offset_histogram
  "warnings":    [str, ...],
  "trustworthy": bool          # False when the alignment looks
                               # cascaded — read this before the
                               # mismatch count, which is meaningless
                               # if the pairing is wrong
}

Ticks mode only — see build_comparison_package.
"""

import json
import os

from trace_diff import diff_traces
from mismatch_report import build_mismatch_summary, require_ticks_mode
from readable_report import build_readable_report
from io_map import (IOMap, make_loom_io_map, io_map_for_program,
                    require_program_match)


def build_comparison_package(program, sim_trace, real_trace,
                              io_map=None, tolerance_ms=50,
                              signals_to_check=None):
    """
    Build a full comparison package from sim and real traces.

    Args:
        program          : str  — ST program name / path
        sim_trace        : list — simulation trace
        real_trace       : list — real trace
        io_map           : IOMap | None
        tolerance_ms     : int  — alignment tolerance
        signals_to_check : list | None — signals to compare

    Returns:
        dict — full comparison package. "trustworthy" is False when
        the underlying alignment looks cascaded; the package is still
        written, but nothing in it should be believed until the
        alignment is explained.

    Note:
        Ticks mode only. Transitions-mode diffs carry edge events,
        which the summary and readable report cannot render — see
        mismatch_report.require_ticks_mode.
    """
    warnings = []

    if io_map is None:
        try:
            io_map = io_map_for_program(program)
        except KeyError as exc:
            io_map = make_loom_io_map()
            warnings.append(str(exc))

    diff_result = diff_traces(sim_trace, real_trace,
                              tolerance_ms=tolerance_ms,
                              signals_to_check=signals_to_check)
    require_ticks_mode(diff_result, "build_comparison_package")

    # The program the traces declare wins over the argument — the
    # traces are the evidence, the argument is a label.
    declared = diff_result.get("program")
    if declared and declared != program:
        warnings.append(
            f"traces declare program {declared} but the package was "
            f"built as {program}; using the declared program"
        )
    effective_program = declared or program

    warnings.extend(require_program_match(io_map, effective_program,
                                          "build_comparison_package"))

    summary  = build_mismatch_summary(diff_result)
    readable = build_readable_report(diff_result, io_map)

    return {
        "program":         effective_program,
        "io_map":          io_map.to_dict(),
        "io_map_manifest": io_map.to_manifest(),
        "sim_trace":       sim_trace,
        "real_trace":      real_trace,
        "diff":            diff_result["mismatches"],
        "summary":         summary,
        "readable_report": readable,
        "offsets":         diff_result["alignment"]["offsets"],
        "warnings":        warnings + diff_result["warnings"],
        "trustworthy":     diff_result["trustworthy"],
    }


def save_comparison_package(package, filepath="outputs/comparison.json"):
    """Save the comparison package to a JSON file."""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath)
                else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(package, f, indent=2)


def load_comparison_package(filepath):
    """Load a comparison package from disk."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def print_comparison_summary(package):
    """Print a compact summary of the comparison package."""
    print("=" * 60)
    print("  COMPARISON PACKAGE SUMMARY")
    print("=" * 60)
    print(f"  Program      : {package['program']}")
    s = package["summary"]
    print(f"  Compared     : {s['total_compared']} signal checks")
    print(f"  Mismatches   : {s['total_mismatches']} ({s['mismatch_rate']}%)")
    r = package["readable_report"]
    print(f"\n  {r['summary']}")
    if r["messages"]:
        print("\n  Details:")
        for msg in r["messages"]:
            print(f"    • {msg}")
    print("=" * 60)


if __name__ == "__main__":
    from sim_trace import load_sim_trace
    from real_trace import create_mock_real_trace

    print("=" * 60)
    print("Phase 7 - Step 10: Export Comparison Package")
    print("=" * 60)

    sim_trace_path = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found — run sim_trace.py first")
        exit(1)

    sim_trace = load_sim_trace(sim_trace_path)
    io_map    = make_loom_io_map()

    # -------------------------------------------------------
    # Package A: clean (no mismatches)
    # -------------------------------------------------------
    print("\n--- Package A: clean run ---")
    real_clean = create_mock_real_trace(sim_trace)
    pkg_a = build_comparison_package(
        program="programs/motor_start.st",
        sim_trace=sim_trace,
        real_trace=real_clean,
        io_map=io_map,
        tolerance_ms=0
    )
    save_comparison_package(pkg_a, "outputs/comparison_clean.json")
    print_comparison_summary(pkg_a)

    # -------------------------------------------------------
    # Package B: with mismatches
    # -------------------------------------------------------
    print("\n--- Package B: with mismatches ---")

    def inject_faults(signals, time):
        signals = dict(signals)
        if time in (500, 600) and "Y0" in signals:
            signals["Y0"] = True   # motor didn't stop after fault
        if time == 300 and "Y1" in signals:
            signals["Y1"] = True   # position indicator wrong
        return signals

    real_faulty = create_mock_real_trace(sim_trace, noise_fn=inject_faults)
    pkg_b = build_comparison_package(
        program="programs/motor_start.st",
        sim_trace=sim_trace,
        real_trace=real_faulty,
        io_map=io_map,
        tolerance_ms=0
    )
    save_comparison_package(pkg_b, "outputs/comparison_faulty.json")
    print_comparison_summary(pkg_b)

    # -------------------------------------------------------
    # Print full JSON for Package B
    # -------------------------------------------------------
    print("\n--- Package B JSON (structure preview) ---")
    preview = {k: v for k, v in pkg_b.items()
               if k not in ("sim_trace", "real_trace", "io_map")}
    print(json.dumps(preview, indent=2))

    # -------------------------------------------------------
    # Verify file structure
    # -------------------------------------------------------
    print("\n--- File Verification ---")
    required_keys = {"program", "io_map", "sim_trace", "real_trace",
                     "diff", "summary", "readable_report"}

    for fname in ("outputs/comparison_clean.json",
                  "outputs/comparison_faulty.json"):
        assert os.path.exists(fname), f"{fname} not found"
        loaded = load_comparison_package(fname)
        missing = required_keys - set(loaded.keys())
        assert not missing, f"{fname} missing keys: {missing}"
        print(f"  PASS — {fname}: valid JSON, all keys present")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Package A: clean
    assert pkg_a["summary"]["total_mismatches"] == 0
    assert pkg_a["readable_report"]["has_mismatches"] is False
    assert pkg_a["diff"] == []
    print("  PASS — Package A: 0 mismatches, diff=[]")

    # Package B: mismatches present
    assert pkg_b["summary"]["total_mismatches"] > 0
    assert pkg_b["readable_report"]["has_mismatches"] is True
    assert len(pkg_b["diff"]) > 0
    assert len(pkg_b["readable_report"]["messages"]) > 0
    print(f"  PASS — Package B: {pkg_b['summary']['total_mismatches']} "
          f"mismatches, {len(pkg_b['diff'])} diff entries")

    # IO map preserved in package
    assert "Y0" in pkg_b["io_map"]
    assert pkg_b["io_map"]["Y0"]["name"] == "Main Motor"
    print("  PASS — IO map preserved in package")

    # Round-trip
    loaded_b = load_comparison_package("outputs/comparison_faulty.json")
    assert loaded_b["summary"] == pkg_b["summary"]
    assert loaded_b["diff"]    == pkg_b["diff"]
    print("  PASS — JSON round-trip identical")

    # --- Transitions-mode rejection + cascade surfacing ---
    from trace_diff import diff_traces as _dt
    tdiff = _dt(sim_trace, real_faulty, tolerance_ms=0, mode="transitions")
    rejected = None
    try:
        build_mismatch_summary(tdiff)
    except ValueError as exc:
        rejected = str(exc)
    assert rejected is not None, "transitions mode must be rejected"
    print("  PASS — transitions-mode diff rejected by the package builders")

    assert "trustworthy" in pkg_a and pkg_a["trustworthy"] is True
    assert "offsets" in pkg_a, "package must carry offset diagnostics"
    print("  PASS — package carries trustworthy flag and offset histogram")

    # --- Program scoping ---
    from trace_aligner import wrap_trace, TS_SCAN
    from io_map import MOTOR_START_PROGRAM, make_shuttle_io_map

    pkg_scoped = build_comparison_package(
        program=MOTOR_START_PROGRAM,
        sim_trace=wrap_trace(sim_trace, TS_SCAN,
                             program=MOTOR_START_PROGRAM),
        real_trace=wrap_trace(real_faulty, TS_SCAN,
                              program=MOTOR_START_PROGRAM),
        io_map=None,               # selected from the declared program
        tolerance_ms=0
    )
    assert pkg_scoped["io_map_manifest"]["program"] == MOTOR_START_PROGRAM
    assert pkg_scoped["program"] == MOTOR_START_PROGRAM
    assert pkg_scoped["readable_report"]["warnings"] == []
    print(f"  PASS — package auto-selected the "
          f"{pkg_scoped['io_map_manifest']['program']} map from provenance")

    wrong_err = None
    try:
        build_comparison_package(
            program=MOTOR_START_PROGRAM,
            sim_trace=wrap_trace(sim_trace, TS_SCAN,
                                 program=MOTOR_START_PROGRAM),
            real_trace=wrap_trace(real_faulty, TS_SCAN,
                                  program=MOTOR_START_PROGRAM),
            io_map=make_shuttle_io_map(),
            tolerance_ms=0)
    except ValueError as exc:
        wrong_err = str(exc)
    assert wrong_err is not None, "wrong-program map must be refused"
    print("  PASS — package refuses an IO map from another program")
