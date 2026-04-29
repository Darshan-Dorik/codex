"""
safety_analyzer.py — Safety Analysis Module

Feeds property violation data to the LLM and asks what unsafe machine
states occurred and how to prevent them.

AI is called ONLY after simulation completes.
AI output is advisory only.
"""

import json
import os
from prompt_builder import build_prompt
from ollama_client import call_llm, is_ollama_available


def analyze_safety(payload, model=None):
    """
    Ask the LLM to explain unsafe states and prevention strategies.

    Args:
        payload : dict — analysis payload
        model   : str  — Ollama model override

    Returns:
        {
          "prompt":   str,
          "insights": str,
          "has_violations": bool,
          "skipped":  bool
        }
    """
    violations = payload.get("violations", [])
    has_violations = len(violations) > 0

    if not has_violations:
        return {
            "prompt":         "",
            "insights":       "No property violations found — no safety concerns.",
            "has_violations": False,
            "skipped":        False
        }

    available, status_msg = is_ollama_available()
    if not available:
        return {
            "prompt":         "",
            "insights":       f"[SKIPPED] Ollama not available: {status_msg}",
            "has_violations": has_violations,
            "skipped":        True
        }

    prompt = build_prompt(payload, task="violations")

    kwargs = {}
    if model:
        kwargs["model"] = model

    insights = call_llm(prompt, **kwargs)

    return {
        "prompt":         prompt,
        "insights":       insights,
        "has_violations": has_violations,
        "skipped":        False
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 6 - Step 6: Safety Analysis Module")
    print("=" * 60)

    # Test 1: payload with violations (shuttle_control)
    json_path = "analysis_shuttle.json"
    if not os.path.exists(json_path):
        print(f"  {json_path} not found — run export_analysis.py first")
        exit(1)

    with open(json_path) as f:
        payload = json.load(f)

    print(f"\nTest 1 — analyze_safety on {json_path}")
    print(f"  Violations in payload: {payload['summary']['violations']}")

    result = analyze_safety(payload)

    if result["skipped"]:
        print(f"  {result['insights']}")
    else:
        print("\n  --- Prompt ---")
        print(result["prompt"])
        print("\n  --- Safety Insights ---")
        print(result["insights"])

    # Test 2: no violations → short-circuit
    print("\nTest 2 — analyze_safety (no violations):")
    if os.path.exists("analysis_motor.json"):
        with open("analysis_motor.json") as f:
            payload_clean = json.load(f)
        result_clean = analyze_safety(payload_clean)
        print(f"  insights: {result_clean['insights']}")
        assert result_clean["has_violations"] is False
        assert "No property violations" in result_clean["insights"]
        print("  PASS — no violations → short-circuit")

    print("\n--- Assertions ---")
    assert result["has_violations"] is True
    if not result["skipped"]:
        assert isinstance(result["insights"], str)
        assert len(result["insights"]) > 20
        assert "PROPERTY VIOLATIONS" in result["prompt"]
        print("  PASS — insights returned, prompt has violations section")
    else:
        print(f"  SKIP — {result['insights']}")
