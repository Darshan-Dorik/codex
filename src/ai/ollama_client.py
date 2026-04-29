"""
ollama_client.py — Ollama LLM Client Wrapper

Provides a single function call_llm(prompt) -> str that sends a prompt
to a local Ollama instance and returns the response text.

Rules:
  - AI is ONLY called after simulation completes — never inside the loop.
  - AI output is advisory only and never modifies simulation state.
  - All simulation results remain deterministic regardless of AI calls.
"""

import json
import urllib.request
import urllib.error


# Default configuration — can be overridden by callers
DEFAULT_MODEL   = "mistral:latest"
DEFAULT_HOST    = "http://localhost:11434"
DEFAULT_TIMEOUT = 600   # seconds — 4 sequential calls on CPU can take ~400s total


def call_llm(prompt, model=DEFAULT_MODEL, host=DEFAULT_HOST,
             timeout=DEFAULT_TIMEOUT):
    """
    Send a prompt to a local Ollama instance and return the response text.

    Args:
        prompt  : str  — the prompt to send
        model   : str  — Ollama model name (default: mistral:latest)
        host    : str  — Ollama base URL (default: http://localhost:11434)
        timeout : int  — request timeout in seconds

    Returns:
        str — the model's response text

    Raises:
        ConnectionError if Ollama is not reachable
        RuntimeError    if the API returns an error response
    """
    url     = f"{host}/api/generate"
    payload = json.dumps({
        "model":  model,
        "prompt": prompt,
        "stream": False          # get full response in one shot
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise ConnectionError(
            f"Cannot reach Ollama at {host}. "
            f"Is it running? (error: {e.reason})"
        ) from e

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Unexpected response from Ollama: {body[:200]}") from e

    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")

    return data.get("response", "").strip()


def is_ollama_available(host=DEFAULT_HOST, timeout=5):
    """
    Check if Ollama is reachable without raising an exception.

    Returns:
        (bool, str) — (available, message)
    """
    try:
        req = urllib.request.Request(f"{host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            return True, f"Ollama available. Models: {models}"
    except Exception as e:
        return False, f"Ollama not available: {e}"


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 6 - Step 1: Ollama Client Wrapper")
    print("=" * 60)

    # --- Check availability ---
    available, msg = is_ollama_available()
    print(f"\n  Ollama status: {msg}")

    if not available:
        print("\n  SKIP — Ollama not running. Start with: ollama serve")
        exit(0)

    # --- Test 1: Simple factual prompt ---
    print("\nTest 1 — Simple prompt:")
    prompt_1 = (
        "In one sentence, what does a PLC (Programmable Logic Controller) do?"
    )
    print(f"  Prompt: {prompt_1}")
    response_1 = call_llm(prompt_1)
    print(f"  Response: {response_1}")

    assert isinstance(response_1, str),  "response must be a string"
    assert len(response_1) > 10,         "response must be non-trivial"
    print("  PASS — response is a non-empty string")

    # --- Test 2: Structured input prompt ---
    print("\nTest 2 — Structured analysis prompt:")
    prompt_2 = (
        "A PLC program has the following safety violation:\n"
        "  - At t=300ms: output Y0 (motor) was True while input X1 (fault sensor) was True.\n"
        "  - Property violated: 'Y0 must not be True when X1 is True'\n\n"
        "In 2-3 sentences, what is the likely root cause?"
    )
    print(f"  Prompt (truncated): {prompt_2[:80]}...")
    response_2 = call_llm(prompt_2)
    print(f"  Response:\n    {response_2}")

    assert isinstance(response_2, str),  "response must be a string"
    assert len(response_2) > 20,         "response must be substantive"
    print("  PASS — structured prompt returns substantive response")

    print("\n  All Step 1 tests passed.")
