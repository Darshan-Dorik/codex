"""
prompt_snapshot.py — Deterministic AI Input Snapshot

Stores the exact prompts sent to the LLM alongside the analysis payload.
This ensures reproducibility: given the same analysis.json, the same
prompts are always generated and can be re-inspected or re-sent.

Snapshot schema:
{
  "source_file": str,
  "prompts": {
    "failures":    str,
    "coverage":    str,
    "suggestions": str,
    "safety":      str
  }
}
"""

import json
import os


def save_prompt_snapshot(report, output_path="prompt_snapshot.json"):
    """
    Save the prompts from an AI report to a JSON snapshot file.

    Args:
        report      : dict — AI report from build_ai_report()
        output_path : str  — output file path

    Returns:
        dict — the snapshot that was saved
    """
    snapshot = {
        "source_file": report.get("program", "unknown"),
        "prompts":     report.get("prompts", {})
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    return snapshot


def load_prompt_snapshot(snapshot_path):
    """Load a previously saved prompt snapshot."""
    with open(snapshot_path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_snapshot_reproducibility(payload, snapshot, task_keys=None):
    """
    Verify that re-building prompts from the same payload produces
    identical prompts to those stored in the snapshot.

    Args:
        payload    : dict — analysis payload
        snapshot   : dict — loaded snapshot
        task_keys  : list — which prompt keys to check (default: all)

    Returns:
        {
          "reproducible": bool,
          "mismatches":   [str, ...]   # keys where prompts differ
        }
    """
    from prompt_builder import build_prompt

    task_map = {
        "failures":    "failures",
        "coverage":    "coverage",
        "suggestions": "suggestions",
        "safety":      "violations"
    }

    if task_keys is None:
        task_keys = list(task_map.keys())

    mismatches = []
    for key in task_keys:
        task = task_map.get(key, "general")
        rebuilt = build_prompt(payload, task=task)
        stored  = snapshot["prompts"].get(key, "")
        if rebuilt != stored:
            mismatches.append(key)

    return {
        "reproducible": len(mismatches) == 0,
        "mismatches":   mismatches
    }


if __name__ == "__main__":
    import json, os
    from ai_report import build_ai_report
    from ollama_client import is_ollama_available

    print("=" * 60)
    print("Phase 6 - Step 9: Deterministic AI Input Snapshot")
    print("=" * 60)

    json_path = "analysis_shuttle.json"
    if not os.path.exists(json_path):
        print(f"  {json_path} not found")
        exit(1)

    with open(json_path) as f:
        payload = json.load(f)

    # Build report (skip LLM calls — we only need prompts for snapshot test)
    from prompt_builder import build_prompt
    print("\nBuilding prompt-only snapshot (no LLM calls needed for this test)...")
    report = {
        "program": payload.get("program", "unknown"),
        "prompts": {
            "failures":    build_prompt(payload, task="failures"),
            "coverage":    build_prompt(payload, task="coverage"),
            "suggestions": build_prompt(payload, task="suggestions"),
            "safety":      build_prompt(payload, task="violations")
        }
    }

    # Save snapshot
    snapshot_path = "prompt_snapshot.json"
    snapshot = save_prompt_snapshot(report, snapshot_path)
    print(f"\nSnapshot saved to: {snapshot_path}")
    print(f"  source_file : {snapshot['source_file']}")
    print(f"  prompt keys : {list(snapshot['prompts'].keys())}")

    # Verify reproducibility — rebuild prompts and compare
    print("\nVerifying reproducibility...")
    check = verify_snapshot_reproducibility(payload, snapshot)
    print(f"  reproducible : {check['reproducible']}")
    if check["mismatches"]:
        print(f"  mismatches   : {check['mismatches']}")

    # Load snapshot back and verify it round-trips correctly
    loaded = load_prompt_snapshot(snapshot_path)
    assert loaded["source_file"] == snapshot["source_file"]
    assert loaded["prompts"].keys() == snapshot["prompts"].keys()

    # Assertions
    print("\n--- Assertions ---")
    assert os.path.exists(snapshot_path),       "snapshot file must exist"
    assert "prompts" in snapshot,               "snapshot must have prompts key"
    assert len(snapshot["prompts"]) == 4,       "snapshot must have 4 prompt keys"
    print("  PASS — snapshot saved with 4 prompt keys")

    assert check["reproducible"] is True,       "prompts must be reproducible"
    assert check["mismatches"] == [],           "no mismatches expected"
    print("  PASS — prompts are deterministically reproducible")

    assert loaded["prompts"] == snapshot["prompts"], "round-trip must be identical"
    print("  PASS — snapshot round-trips correctly from disk")
