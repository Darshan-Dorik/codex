"""
scenario_suggester.py — Test Scenario Suggestion Module

Feeds coverage gap data to the LLM and asks it to suggest new test
scenarios that would exercise the missing branches.

AI is called ONLY after simulation completes.
AI output is advisory only — suggestions are human-readable text,
not executable scenario dicts.
"""

import json
import os
from prompt_builder import build_prompt
from ollama_client import call_llm, is_ollama_available


def suggest_scenarios(payload, model=None):
    """
    Ask the LLM to suggest new test scenarios for uncovered branches.

    Args:
        payload : dict — analysis payload (from analysis.json)
        model   : str  — Ollama model override (None = use default)

    Returns:
        {
          "prompt":      str,   # exact prompt sent to LLM
          "suggestions": str,   # LLM response text (human-readable list)
          "has_gaps":    bool,
          "skipped":     bool   # True if Ollama unavailable
        }
    """
    gaps = payload.get("coverage_gaps", {})
    has_gaps = any([
        gaps.get("conditions_never_true"),
        gaps.get("conditions_never_false"),
        gaps.get("branches_never_then"),
        gaps.get("branches_never_else")
    ])

    if not has_gaps:
        return {
            "prompt":      "",
            "suggestions": "No coverage gaps found — no new scenarios needed.",
            "has_gaps":    False,
            "skipped":     False
        }

    available, status_msg = is_ollama_available()
    if not available:
        return {
            "prompt":      "",
            "suggestions": f"[SKIPPED] Ollama not available: {status_msg}",
            "has_gaps":    has_gaps,
            "skipped":     True
        }

    prompt = build_prompt(payload, task="suggestions")

    kwargs = {}
    if model:
        kwargs["model"] = model

    suggestions = call_llm(prompt, **kwargs)

    return {
        "prompt":      prompt,
        "suggestions": suggestions,
        "has_gaps":    has_gaps,
        "skipped":     False
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 6 - Step 5: Test Scenario Suggestion")
    print("=" * 60)

    # -------------------------------------------------------
    # Build a payload with coverage gaps
    # (motor_start.st — ELSE branch never executed)
    # -------------------------------------------------------
    from scenario_template import expand_template
    from batch_executor import execute_scenarios_from_file
    from analysis_payload import build_analysis_payload

    partial = expand_template({
        "name": "SuggestTest",
        "inputs": ["X0", "X1"],
        "timing": [300],
        "variations": [
            {
                "__initial__": {"X0": True, "X1": False},
                "X0": True, "X1": False   # condition always True → ELSE never hit
            }
        ],
        "expected": []
    })

    batch = execute_scenarios_from_file(
        st_file="programs/motor_start.st",
        scenarios=partial,
        max_time_ms=500, step_ms=100
    )
    payload_gap = build_analysis_payload("programs/motor_start.st", batch["results"])

    print(f"\n  Coverage gaps:")
    g = payload_gap["coverage_gaps"]
    print(f"    conditions_never_false : {g['conditions_never_false']}")
    print(f"    branches_never_else    : {g['branches_never_else']}")

    # -------------------------------------------------------
    # Test 1: payload WITH gaps → LLM suggestions
    # -------------------------------------------------------
    print("\nTest 1 — suggest_scenarios (gaps present):")
    result = suggest_scenarios(payload_gap)

    if result["skipped"]:
        print(f"  {result['suggestions']}")
    else:
        print("\n  --- Prompt sent to LLM ---")
        print(result["prompt"])
        print("\n  --- LLM Scenario Suggestions ---")
        print(result["suggestions"])

    # -------------------------------------------------------
    # Test 2: payload WITHOUT gaps → short-circuit
    # -------------------------------------------------------
    print("\nTest 2 — suggest_scenarios (no gaps):")
    if os.path.exists("analysis_motor.json"):
        with open("analysis_motor.json") as f:
            payload_clean = json.load(f)
        result_clean = suggest_scenarios(payload_clean)
        print(f"  suggestions: {result_clean['suggestions']}")
        assert result_clean["has_gaps"] is False
        assert "no new scenarios needed" in result_clean["suggestions"].lower()
        print("  PASS — no gaps → short-circuit, no LLM call")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert result["has_gaps"] is True, "payload must have gaps"

    if not result["skipped"]:
        assert isinstance(result["suggestions"], str), "suggestions must be str"
        assert len(result["suggestions"]) > 20,        "suggestions must be substantive"
        assert len(result["prompt"]) > 50,             "prompt must be non-trivial"
        assert "COVERAGE GAPS" in result["prompt"],    "prompt must include gap section"
        assert "Suggest" in result["prompt"],          "prompt must ask for suggestions"
        print("  PASS — suggestions is a non-empty string")
        print("  PASS — prompt includes COVERAGE GAPS + suggestion question")
        print("  PASS — has_gaps=True correctly detected")
    else:
        print(f"  SKIP — {result['suggestions']}")
