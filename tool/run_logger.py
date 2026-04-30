"""
tool/run_logger.py — Run Logging System

Appends a structured log entry for every validation run to a
persistent log file (outputs/run_log.jsonl).

Each entry is one JSON object per line (JSONL format) containing:
  - timestamp
  - config file used
  - program validated
  - result summary
  - output directory

JSONL is used so the log file can be appended to indefinitely
without loading the entire file into memory.
"""

import json
import os
from datetime import datetime


DEFAULT_LOG_PATH = "outputs/run_log.jsonl"


def log_run(config, pipeline_result, run_dir=None,
            log_path=DEFAULT_LOG_PATH):
    """
    Append a log entry for a completed run.

    Args:
        config          : dict — the config used
        pipeline_result : dict — from run_pipeline()
        run_dir         : str | None — output directory for this run
        log_path        : str — path to the JSONL log file

    Returns:
        dict — the log entry that was written
    """
    agg = pipeline_result.get("aggregation", {})

    entry = {
        "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config_file":  config.get("_source_path", "(in-memory)"),
        "program":      pipeline_result.get("program", "?"),
        "status":       pipeline_result.get("status", "unknown"),
        "scenarios_run": pipeline_result.get("scenarios_run", 0),
        "passed":       agg.get("passed",     0),
        "failed":       agg.get("failed",     0),
        "violations":   agg.get("violations", 0),
        "cal_score":    (pipeline_result.get("calibration") or {}).get("score"),
        "output_dir":   run_dir,
        "error":        pipeline_result.get("error")
    }

    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path)
                else ".", exist_ok=True)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def read_log(log_path=DEFAULT_LOG_PATH):
    """
    Read all log entries from the JSONL log file.

    Returns:
        list of dicts — all log entries (oldest first)
    """
    if not os.path.exists(log_path):
        return []

    entries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass   # skip malformed lines
    return entries


def print_log_tail(log_path=DEFAULT_LOG_PATH, n=10):
    """Print the last N log entries in a readable format."""
    entries = read_log(log_path)
    if not entries:
        print("  (log is empty)")
        return

    shown = entries[-n:]
    print(f"  Last {len(shown)} run(s) (of {len(entries)} total):")
    print(f"  {'Timestamp':>20}  {'Status':>8}  {'Pass':>5}  "
          f"{'Fail':>5}  {'Viol':>5}  Program")
    print("  " + "-" * 72)
    for e in shown:
        prog = os.path.basename(e.get("program", "?"))
        print(f"  {e['timestamp']:>20}  {e['status']:>8}  "
              f"{e['passed']:>5}  {e['failed']:>5}  "
              f"{e['violations']:>5}  {prog}")


if __name__ == "__main__":
    import sys

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _subdir in ("", "src/core", "src/testing", "src/batch",
                    "src/analysis", "src/ai", "tool"):
        _p = os.path.join(_ROOT, _subdir)
        if _p not in sys.path:
            sys.path.insert(0, _p)

    from config_loader import load_config
    from orchestrator  import run_pipeline

    print("=" * 60)
    print("Phase 10 - Step 7: Logging System")
    print("=" * 60)

    TEST_LOG = "outputs/test_run_log.jsonl"

    # Clean up any previous test log
    if os.path.exists(TEST_LOG):
        os.remove(TEST_LOG)

    config = load_config("outputs/test_config.json")
    config["_source_path"] = "outputs/test_config.json"

    # -------------------------------------------------------
    # Test 1: log a successful run
    # -------------------------------------------------------
    print("\nTest 1 — Log a successful run:")
    result1 = run_pipeline(config, verbose=False)
    entry1  = log_run(config, result1,
                      run_dir="outputs/runs/test_run/20260430_120000",
                      log_path=TEST_LOG)
    print(f"  Logged: {entry1}")

    # -------------------------------------------------------
    # Test 2: log an error run
    # -------------------------------------------------------
    print("\nTest 2 — Log an error run:")
    error_result = {
        "status": "error",
        "error":  "ST file not found: programs/missing.st",
        "program": "programs/missing.st",
        "scenarios_run": 0,
        "results": [], "aggregation": {},
        "calibration": None, "ai_report": None
    }
    entry2 = log_run(config, error_result, log_path=TEST_LOG)
    print(f"  Logged: {entry2}")

    # -------------------------------------------------------
    # Test 3: log a third run and read back
    # -------------------------------------------------------
    result3 = run_pipeline(config, verbose=False)
    log_run(config, result3, log_path=TEST_LOG)

    print("\nTest 3 — Read log back:")
    entries = read_log(TEST_LOG)
    print(f"  Total entries: {len(entries)}")
    print()
    print_log_tail(TEST_LOG, n=5)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert os.path.exists(TEST_LOG),            "log file must exist"
    print(f"  PASS — log file created: {TEST_LOG}")

    assert len(entries) == 3,                   "must have 3 entries"
    print("  PASS — 3 entries logged")

    # Entry 1: successful run
    assert entries[0]["status"]     == "success"
    assert entries[0]["passed"]     == 4
    assert entries[0]["violations"] == 0
    assert entries[0]["output_dir"] == "outputs/runs/test_run/20260430_120000"
    print("  PASS — entry 1: success, passed=4, violations=0")

    # Entry 2: error run
    assert entries[1]["status"] == "error"
    assert entries[1]["error"]  is not None
    print("  PASS — entry 2: error logged with message")

    # All entries have required fields
    required = {"timestamp", "config_file", "program", "status",
                "scenarios_run", "passed", "failed", "violations"}
    for e in entries:
        missing = required - set(e.keys())
        assert not missing, f"missing fields: {missing}"
    print("  PASS — all entries have required fields")

    # JSONL format: each line is valid JSON
    with open(TEST_LOG) as f:
        lines = [l.strip() for l in f if l.strip()]
    assert all(json.loads(l) for l in lines), "all lines must be valid JSON"
    print("  PASS — JSONL format: all lines are valid JSON")
