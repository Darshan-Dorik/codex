"""
prompt_limiter.py — Prompt Size Control

Ensures prompts stay within a safe token limit before sending to the LLM.
Uses a conservative character-based estimate (1 token ≈ 4 chars).

Trimming strategy:
  1. Cap number of failures included
  2. Cap violation examples per property
  3. Hard-truncate the final prompt string if still over limit
"""

from prompt_builder import build_prompt

# Conservative estimate: 1 token ≈ 4 characters
CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS = 2048   # safe limit for 7B models
DEFAULT_MAX_CHARS  = DEFAULT_MAX_TOKENS * CHARS_PER_TOKEN  # 8192 chars


def estimate_tokens(text):
    """Estimate token count from character count."""
    return len(text) // CHARS_PER_TOKEN


def build_limited_prompt(payload, task="general", max_tokens=DEFAULT_MAX_TOKENS):
    """
    Build a prompt that fits within max_tokens.

    Tries progressively smaller failure/violation counts until the prompt
    fits, then hard-truncates if still over limit.

    Args:
        payload    : dict — analysis payload
        task       : str  — prompt task type
        max_tokens : int  — token budget

    Returns:
        {
          "prompt":          str,
          "estimated_tokens": int,
          "max_failures_used": int,
          "truncated":        bool   # True if hard truncation was applied
        }
    """
    max_chars = max_tokens * CHARS_PER_TOKEN

    # Try reducing max_failures from 5 down to 1
    for max_failures in (5, 3, 2, 1):
        prompt = build_prompt(payload, max_failures=max_failures,
                              max_violations_per_property=2, task=task)
        if len(prompt) <= max_chars:
            return {
                "prompt":            prompt,
                "estimated_tokens":  estimate_tokens(prompt),
                "max_failures_used": max_failures,
                "truncated":         False
            }

    # Hard truncate as last resort — keep a note at the end
    prompt = build_prompt(payload, max_failures=1,
                          max_violations_per_property=1, task=task)
    if len(prompt) > max_chars:
        truncation_note = "\n[TRUNCATED: prompt exceeded token limit]"
        prompt = prompt[:max_chars - len(truncation_note)] + truncation_note

    return {
        "prompt":            prompt,
        "estimated_tokens":  estimate_tokens(prompt),
        "max_failures_used": 1,
        "truncated":         True
    }


if __name__ == "__main__":
    import json, os

    print("=" * 60)
    print("Phase 6 - Step 8: Prompt Size Control")
    print("=" * 60)

    json_path = "analysis_shuttle.json"
    if not os.path.exists(json_path):
        print(f"  {json_path} not found")
        exit(1)

    with open(json_path) as f:
        payload = json.load(f)

    # Test 1: normal limit — should fit easily
    print("\nTest 1 — normal limit (2048 tokens):")
    r1 = build_limited_prompt(payload, task="general", max_tokens=2048)
    print(f"  estimated_tokens : {r1['estimated_tokens']}")
    print(f"  max_failures_used: {r1['max_failures_used']}")
    print(f"  truncated        : {r1['truncated']}")
    print(f"  prompt length    : {len(r1['prompt'])} chars")

    # Test 2: very tight limit — forces truncation
    print("\nTest 2 — very tight limit (100 tokens = 400 chars):")
    r2 = build_limited_prompt(payload, task="general", max_tokens=100)
    print(f"  estimated_tokens : {r2['estimated_tokens']}")
    print(f"  truncated        : {r2['truncated']}")
    print(f"  prompt length    : {len(r2['prompt'])} chars")
    print(f"  prompt tail      : ...{r2['prompt'][-60:]!r}")

    # Test 3: medium limit — reduces failures
    print("\nTest 3 — medium limit (512 tokens):")
    r3 = build_limited_prompt(payload, task="failures", max_tokens=512)
    print(f"  estimated_tokens : {r3['estimated_tokens']}")
    print(f"  max_failures_used: {r3['max_failures_used']}")
    print(f"  truncated        : {r3['truncated']}")

    # Assertions
    print("\n--- Assertions ---")
    assert r1["estimated_tokens"] <= 2048,  "Test 1: must fit in 2048 tokens"
    assert r1["truncated"] is False,        "Test 1: no truncation needed"
    print("  PASS — Test 1: fits within 2048 tokens, no truncation")

    assert r2["truncated"] is True,         "Test 2: must be truncated"
    assert len(r2["prompt"]) <= 400 + 50,   "Test 2: prompt near 400 chars"
    assert "TRUNCATED" in r2["prompt"],     "Test 2: truncation note present"
    print("  PASS — Test 2: hard truncation applied, note present")

    assert r3["estimated_tokens"] <= 512,   "Test 3: must fit in 512 tokens"
    print(f"  PASS — Test 3: fits in 512 tokens "
          f"(max_failures={r3['max_failures_used']})")
