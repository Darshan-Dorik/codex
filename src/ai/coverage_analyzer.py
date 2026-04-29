"""
coverage_analyzer.py — Coverage Analysis Module

Feeds coverage gap data from an analysis payload to the LLM and returns
reasoning about which conditions are untested and why that is risky.

AI is called ONLY after simulation completes.
AI output is advisory only — it never modifies simulation state.
"""

import json
import os
from prompt_builder import build_prompt
from ollama_client import call_llm, is_ollama_available


def analyze_coverage(payload, model=None):
    """
    Ask the LLM to reason about coverage gaps in the analysis payload.

    Args:
        payload : dict — analysis payload (from analysis.json)
        model   : str  — Ollama model override (None = use default)

    Returns:
        {
          "prompt":    str,   # exact prompt sent to LLM
          "analysis":  str,   # LLM response text
          "has_gaps":  bool,  # whether gaps were present in payload
          "skipped":   bool   # True if Ollama unavailable
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
            "prompt":   "",
            "analysis": "No coverage gaps found in analysis payload.",
            "has_gaps": False,
            "skipped":  False
        }

    available, status_msg = is_ollama_available()
    if not available:
        return {
            "prompt":   "",
            "analysis": f"[SKIPPED] Ollama not available: {status_msg}",
            "has_gaps": has_gaps,
            "skipped":  True
        }

    prompt = build_prompt(payload, task="coverage")

    kwargs = {}
    if model:
        kwargs["model"] = model

    analysis = call_llm(prompt, **kwargs)

    return {
        "prompt":   prompt,
        "analysis": analysis,
        "has_gaps": has_gaps,
        "skipped":  False
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 6 - Step 4: Coverage Analysis Module")
    print("=" * 60)

    # -------------------------------------------------------
    # Build a payload that has coverage gaps for testing
    # (re-run the partial scenario from Phase 5 Step 7)
    # -------------------------------------------------------
    from scenario_template import expand_template
    from batch_executor import execute_scenarios_from_file
    from analysis_payload import build_analysis_payload

    partial = expand_template({
        "name": "PartialCov",
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

    print(f"\n  Coverage gaps in test payload:")
    g = payload_gap["coverage_gaps"]
    print(f"    conditions_never_false : {g['conditions_never_false']}")
    print(f"    branches_never_else    : {g['branches_never_else']}")

    # -------------------------------------------------------
    # Test 1: payload WITH gaps → LLM call
    # -------------------------------------------------------
    print("\nTest 1 — analyze_coverage (gaps present):")
    result = analyze_coverage(payload_gap)

    if result["skipped"]:
        print(f"  {result['analysis']}")
    else:
        print("\n  --- Prompt sent to LLM ---")
        print(result["prompt"])
        print("\n  --- LLM Coverage Analysis ---")
        print(result["analysis"])

    # -------------------------------------------------------
    # Test 2: payload WITHOUT gaps → short-circuit
    # -------------------------------------------------------
    print("\nTest 2 — analyze_coverage (no gaps, motor_start full run):")
    if os.path.exists("analysis_motor.json"):
        with open("analysis_motor.json") as f:
            payload_clean = json.load(f)
        result_clean = analyze_coverage(payload_clean)
        print(f"  analysis: {result_clean['analysis']}")
        assert result_clean["has_gaps"] is False
        assert "No coverage gaps" in result_clean["analysis"]
        print("  PASS — no gaps → short-circuit, no LLM call")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert result["has_gaps"] is True,          "payload must have gaps"

    if not result["skipped"]:
        assert isinstance(result["analysis"], str), "analysis must be str"
        assert len(result["analysis"]) > 20,        "analysis must be substantive"
        assert len(result["prompt"]) > 50,          "prompt must be non-trivial"
        assert "COVERAGE GAPS" in result["prompt"], "prompt must include gap section"
        print("  PASS — analysis is a non-empty string")
        print("  PASS — prompt includes COVERAGE GAPS section")
        print(f"  PASS — has_gaps=True correctly detected")
    else:
        print(f"  SKIP — {result['analysis']}")
