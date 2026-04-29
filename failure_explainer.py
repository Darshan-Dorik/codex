"""
failure_explainer.py — Failure Explanation Module

Feeds failure data from an analysis payload to the LLM and returns
a structured explanation of possible root causes.

AI is called ONLY after simulation completes.
AI output is advisory only — it never modifies simulation state.
"""

import json
from prompt_builder import build_prompt
from ollama_client import call_llm, is_ollama_available


def explain_failures(payload, max_failures=3, model=None):
    """
    Ask the LLM to explain root causes of failures in the analysis payload.

    Args:
        payload      : dict — analysis payload (from analysis.json)
        max_failures : int  — max failures to include in prompt
        model        : str  — Ollama model override (None = use default)

    Returns:
        {
          "prompt":      str,   # exact prompt sent to LLM
          "explanation": str,   # LLM response text
          "failures_included": int,
          "skipped": bool       # True if Ollama unavailable
        }
    """
    failures = payload.get("failures", [])

    if not failures:
        return {
            "prompt":      "",
            "explanation": "No failures found in analysis payload.",
            "failures_included": 0,
            "skipped": False
        }

    available, status_msg = is_ollama_available()
    if not available:
        return {
            "prompt":      "",
            "explanation": f"[SKIPPED] Ollama not available: {status_msg}",
            "failures_included": 0,
            "skipped": True
        }

    prompt = build_prompt(payload, max_failures=max_failures, task="failures")

    kwargs = {}
    if model:
        kwargs["model"] = model

    explanation = call_llm(prompt, **kwargs)

    return {
        "prompt":            prompt,
        "explanation":       explanation,
        "failures_included": min(len(failures), max_failures),
        "skipped":           False
    }


if __name__ == "__main__":
    import os

    print("=" * 60)
    print("Phase 6 - Step 3: Failure Explanation Module")
    print("=" * 60)

    # -------------------------------------------------------
    # Test 1: payload with violations (shuttle_control)
    # -------------------------------------------------------
    json_path = "analysis_shuttle.json"
    if not os.path.exists(json_path):
        print(f"  {json_path} not found — run export_analysis.py first")
        exit(1)

    with open(json_path) as f:
        payload = json.load(f)

    print(f"\nTest 1 — explain_failures on {json_path}")
    print(f"  Failures in payload: {len(payload.get('failures', []))}")

    result = explain_failures(payload, max_failures=3)

    if result["skipped"]:
        print(f"  {result['explanation']}")
    else:
        print(f"\n  --- Prompt sent to LLM ---")
        print(result["prompt"])
        print(f"\n  --- LLM Explanation ---")
        print(result["explanation"])
        print(f"\n  failures_included: {result['failures_included']}")

    # -------------------------------------------------------
    # Test 2: payload with no failures (motor_start — clean run)
    # -------------------------------------------------------
    json_path_clean = "analysis_motor.json"
    if os.path.exists(json_path_clean):
        with open(json_path_clean) as f:
            payload_clean = json.load(f)

        print(f"\nTest 2 — explain_failures on {json_path_clean} (no failures)")
        result_clean = explain_failures(payload_clean)
        print(f"  explanation: {result_clean['explanation']}")
        assert result_clean["failures_included"] == 0
        assert "No failures" in result_clean["explanation"]
        print("  PASS — no failures → short-circuit response, no LLM call")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    if not result["skipped"]:
        assert isinstance(result["explanation"], str),  "explanation must be str"
        assert len(result["explanation"]) > 20,         "explanation must be substantive"
        assert result["failures_included"] >= 1,        "at least 1 failure included"
        assert "prompt" in result,                      "result must have prompt key"
        assert len(result["prompt"]) > 50,              "prompt must be non-trivial"
        print("  PASS — explanation is a non-empty string")
        print("  PASS — prompt was built and stored")
        print(f"  PASS — failures_included={result['failures_included']}")
    else:
        print(f"  SKIP — Ollama not available: {result['explanation']}")
