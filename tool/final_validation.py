"""
tool/final_validation.py — Final Integration Test

Exercises the complete loom-validate pipeline end-to-end:
  1. --list-presets
  2. --dry-run on a preset
  3. Full run on motor_start_basic preset
  4. Full run on shuttle_control_full preset (expects violations)
  5. Error handling (bad config)
  6. Log file verification

This is the acceptance test for Phase 10.
"""

import sys
import os
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOL = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, _TOOL,
           os.path.join(_ROOT, "src/core"),
           os.path.join(_ROOT, "src/testing"),
           os.path.join(_ROOT, "src/batch"),
           os.path.join(_ROOT, "src/analysis"),
           os.path.join(_ROOT, "src/ai")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tool.loom_validate import main as loom_validate_main
from tool.run_logger    import read_log


def run_cmd(argv, expect_exit=0):
    """Run loom_validate_main with given argv, assert exit code."""
    print(f"\n  $ loom-validate {' '.join(argv)}")
    print("  " + "-" * 56)
    code = loom_validate_main(argv)
    status = "OK" if code == expect_exit else "UNEXPECTED"
    print(f"  exit code: {code}  [{status}]")
    return code


if __name__ == "__main__":
    print("=" * 60)
    print("  PHASE 10 - STEP 10: FINAL VALIDATION RUN")
    print("=" * 60)

    TEST_LOG = "outputs/final_validation_log.jsonl"
    # Clean previous test log
    if os.path.exists(TEST_LOG):
        os.remove(TEST_LOG)

    results = {}

    # -------------------------------------------------------
    # Test 1: --list-presets
    # -------------------------------------------------------
    print("\n[1/6] List presets:")
    code = run_cmd(["--list-presets"])
    results["list_presets"] = code == 0

    # -------------------------------------------------------
    # Test 2: --dry-run on motor_start_basic preset
    # -------------------------------------------------------
    print("\n[2/6] Dry run on motor_start_basic preset:")
    code = run_cmd(["--preset", "motor_start_basic", "--dry-run"])
    results["dry_run_preset"] = code == 0

    # -------------------------------------------------------
    # Test 3: Full run on motor_start_basic (expect PASS)
    # -------------------------------------------------------
    print("\n[3/6] Full run — motor_start_basic (expect: ALL CHECKS PASSED):")
    code = run_cmd(["--preset", "motor_start_basic"])
    results["motor_start_run"] = code == 0

    # -------------------------------------------------------
    # Test 4: Full run on shuttle_control_full (expect violations)
    # -------------------------------------------------------
    print("\n[4/6] Full run — shuttle_control_full (expect: violations):")
    code = run_cmd(["--preset", "shuttle_control_full"])
    # Exit 0 even with violations (violations are advisory, not fatal)
    results["shuttle_run"] = code == 0

    # -------------------------------------------------------
    # Test 5: Error handling — nonexistent config
    # -------------------------------------------------------
    print("\n[5/6] Error handling — nonexistent config (expect: exit 1):")
    code = run_cmd(["outputs/nonexistent_config.json"], expect_exit=1)
    results["error_handling"] = code == 1

    # -------------------------------------------------------
    # Test 6: Verify log file was written
    # -------------------------------------------------------
    print("\n[6/6] Verify run log:")
    entries = read_log()   # default log path
    print(f"  Total log entries: {len(entries)}")
    if entries:
        print(f"  Last entry: status={entries[-1]['status']} "
              f"program={os.path.basename(entries[-1]['program'])}")
    results["log_written"] = len(entries) >= 2   # at least 2 full runs logged

    # -------------------------------------------------------
    # Final summary
    # -------------------------------------------------------
    print()
    print("=" * 60)
    print("  FINAL VALIDATION RESULTS")
    print("=" * 60)
    all_passed = True
    for test, passed in results.items():
        icon = "✓" if passed else "✗"
        print(f"  [{icon}]  {test}")
        if not passed:
            all_passed = False

    print("-" * 60)
    total  = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"  {passed}/{total} tests passed")
    print("=" * 60)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert results["list_presets"],     "list_presets must succeed"
    print("  PASS — --list-presets works")

    assert results["dry_run_preset"],   "dry_run_preset must succeed"
    print("  PASS — --dry-run on preset works")

    assert results["motor_start_run"],  "motor_start full run must succeed"
    print("  PASS — motor_start_basic full run: exit 0")

    assert results["shuttle_run"],      "shuttle_control full run must exit 0"
    print("  PASS — shuttle_control_full full run: exit 0")

    assert results["error_handling"],   "bad config must exit 1"
    print("  PASS — error handling: bad config exits 1")

    assert results["log_written"],      "run log must have entries"
    print(f"  PASS — run log has {len(entries)} entries")

    # Verify output files exist for motor_start run
    motor_run_base = "outputs/runs/motor_start_basic"
    assert os.path.isdir(motor_run_base), \
        f"output dir must exist: {motor_run_base}"
    # Find the timestamped subdirectory
    subdirs = [d for d in os.listdir(motor_run_base)
               if os.path.isdir(os.path.join(motor_run_base, d))]
    assert subdirs, "must have at least one timestamped run dir"
    latest = sorted(subdirs)[-1]
    run_dir = os.path.join(motor_run_base, latest)
    assert os.path.exists(os.path.join(run_dir, "report.json")),     "report.json"
    assert os.path.exists(os.path.join(run_dir, "run_config.json")), "run_config.json"
    print(f"  PASS — output files exist in {run_dir}")

    # -------------------------------------------------------
    # Shim: the two faces must project the SAME signals.
    #
    # This lives here, not only in nodeset_export's own tests, because
    # final_validation is what someone runs before committing — and
    # drift between the Modbus register map and the OPC UA model is
    # exactly the kind of thing that gets committed when the only check
    # is inside the module that caused it. Build-time: no twin, no
    # socket, no thread, so it runs in CI.
    # -------------------------------------------------------
    print("\n  Shim: Modbus / OPC UA face parity")
    from tool.loom_shim import check_faces_cover_same_signals

    parity = check_faces_cover_same_signals()
    for err in parity["errors"]:
        print(f"    FAIL — {err}")
    assert parity["ok"], f"shim faces disagree: {parity['errors']}"
    print(f"  PASS — {parity['signals']} signals project to "
          f"{parity['registers']} Modbus registers and "
          f"{parity['signals']} OPC UA variables "
          f"({', '.join(parity['units'])})")

    print()
    if all_passed:
        print("  ✓  ALL PHASE 10 TESTS PASSED — system is production-ready")
    else:
        print("  ✗  SOME TESTS FAILED")
    sys.exit(0 if all_passed else 1)
