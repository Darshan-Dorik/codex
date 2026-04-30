"""
tool/error_handler.py — Error Handling System

Provides a centralised error classification and formatting layer.
All errors are caught, classified, and presented as clean messages
— no raw stack traces shown to the operator.

Error categories:
  CONFIG   — config file problems (missing, invalid JSON, bad fields)
  FILE     — file not found or unreadable
  PARSE    — ST parsing failures
  RUNTIME  — unexpected errors during simulation
  AI       — AI analysis failures (non-fatal)
"""

import sys
import os
import traceback


# ---------------------------------------------------------------------------
# Error categories
# ---------------------------------------------------------------------------

class LoomValidateError(Exception):
    """Base class for all tool-level errors."""
    category = "ERROR"

class ConfigError(LoomValidateError):
    category = "CONFIG"

class FileError(LoomValidateError):
    category = "FILE"

class ParseError(LoomValidateError):
    category = "PARSE"

class RuntimeError_(LoomValidateError):
    """Named RuntimeError_ to avoid shadowing Python built-in."""
    category = "RUNTIME"

class AIError(LoomValidateError):
    """Non-fatal — AI analysis failed but pipeline can continue."""
    category = "AI"


# ---------------------------------------------------------------------------
# Error classifier
# ---------------------------------------------------------------------------

def classify_error(exc):
    """
    Map any exception to a (category, message) tuple.

    Args:
        exc : Exception

    Returns:
        (str, str) — (category, human-readable message)
    """
    if isinstance(exc, LoomValidateError):
        return exc.category, str(exc)

    # Map common Python exceptions to categories
    exc_type = type(exc).__name__
    msg      = str(exc)

    if isinstance(exc, FileNotFoundError):
        return "FILE", f"File not found: {msg}"

    if isinstance(exc, PermissionError):
        return "FILE", f"Permission denied: {msg}"

    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "PARSE", f"Data error ({exc_type}): {msg}"

    if isinstance(exc, SyntaxError):
        return "PARSE", f"Syntax error: {msg}"

    # Catch-all
    return "RUNTIME", f"Unexpected error ({exc_type}): {msg}"


def format_error(category, message, debug=False, exc=None):
    """
    Format an error for display.

    Args:
        category : str       — error category
        message  : str       — human-readable message
        debug    : bool      — if True, include traceback
        exc      : Exception — original exception (for traceback)

    Returns:
        str — formatted error text
    """
    lines = [f"{category} ERROR: {message}"]

    if debug and exc is not None:
        lines.append("")
        lines.append("--- Debug traceback ---")
        lines.append(traceback.format_exc().strip())

    return "\n".join(lines)


def handle_error(exc, debug=False, stream=None):
    """
    Classify, format, and print an error.

    Args:
        exc    : Exception
        debug  : bool — include traceback
        stream : file-like — defaults to sys.stderr

    Returns:
        int — exit code (always 1)
    """
    if stream is None:
        stream = sys.stderr

    category, message = classify_error(exc)
    text = format_error(category, message, debug=debug, exc=exc)
    print(text, file=stream)
    return 1


# ---------------------------------------------------------------------------
# Safe wrappers
# ---------------------------------------------------------------------------

def safe_load_config(filepath, debug=False):
    """
    Load config with clean error handling.

    Returns:
        (config, None) on success
        (None, error_text) on failure
    """
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(_ROOT, "tool"))
    from config_loader import load_config
    from config_loader import ConfigError as _ConfigError

    try:
        return load_config(filepath), None
    except _ConfigError as e:
        return None, format_error("CONFIG", str(e), debug=debug, exc=e)
    except Exception as e:
        cat, msg = classify_error(e)
        return None, format_error(cat, msg, debug=debug, exc=e)


def safe_run_pipeline(config, verbose=True, debug=False):
    """
    Run pipeline with clean error handling.

    Returns:
        (result, None) on success
        (None, error_text) on failure
    """
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _subdir in ("", "src/core", "src/testing", "src/batch",
                    "src/analysis", "src/ai", "tool"):
        _p = os.path.join(_ROOT, _subdir)
        if _p not in sys.path:
            sys.path.insert(0, _p)

    from orchestrator import run_pipeline

    try:
        result = run_pipeline(config, verbose=verbose)
        if result["status"] == "error":
            cat, msg = classify_error(Exception(result["error"]))
            return None, format_error("RUNTIME", result["error"],
                                      debug=debug)
        return result, None
    except Exception as e:
        cat, msg = classify_error(e)
        return None, format_error(cat, msg, debug=debug, exc=e)


if __name__ == "__main__":
    import json

    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _subdir in ("", "src/core", "src/testing", "src/batch",
                    "src/analysis", "src/ai", "tool"):
        _p = os.path.join(_ROOT, _subdir)
        if _p not in sys.path:
            sys.path.insert(0, _p)

    print("=" * 60)
    print("Phase 10 - Step 6: Error Handling System")
    print("=" * 60)

    # -------------------------------------------------------
    # Test 1: config file not found
    # -------------------------------------------------------
    print("\nTest 1 — Config file not found:")
    cfg, err = safe_load_config("outputs/nonexistent.json")
    print(f"  {err}")

    # -------------------------------------------------------
    # Test 2: invalid JSON
    # -------------------------------------------------------
    print("\nTest 2 — Invalid JSON:")
    bad_json = "outputs/bad_json_test.json"
    with open(bad_json, "w") as f:
        f.write("{ not valid json }")
    cfg, err = safe_load_config(bad_json)
    print(f"  {err}")

    # -------------------------------------------------------
    # Test 3: missing required field
    # -------------------------------------------------------
    print("\nTest 3 — Missing required field:")
    bad_cfg = {"output_dir": "outputs/x", "scenarios": {
        "inputs": ["X0"], "timing": [100],
        "max_scenarios": 4, "step_ms": 100
    }}
    bad_cfg_path = "outputs/bad_cfg_test.json"
    with open(bad_cfg_path, "w") as f:
        json.dump(bad_cfg, f)
    cfg, err = safe_load_config(bad_cfg_path)
    print(f"  {err}")

    # -------------------------------------------------------
    # Test 4: bad program path in pipeline
    # -------------------------------------------------------
    print("\nTest 4 — Bad program path in pipeline:")
    from config_loader import load_config
    good_cfg = load_config("outputs/test_config.json")
    bad_prog_cfg = dict(good_cfg)
    bad_prog_cfg["program"] = "programs/nonexistent.st"
    result, err = safe_run_pipeline(bad_prog_cfg, verbose=False)
    print(f"  {err}")

    # -------------------------------------------------------
    # Test 5: classify_error maps correctly
    # -------------------------------------------------------
    print("\nTest 5 — classify_error mapping:")
    cases = [
        (FileNotFoundError("test.st"),  "FILE"),
        (ValueError("bad value"),       "PARSE"),
        (KeyError("missing_key"),       "PARSE"),
        (Exception("unexpected"),       "RUNTIME"),
    ]
    for exc, expected_cat in cases:
        cat, msg = classify_error(exc)
        print(f"  {type(exc).__name__:25} → {cat}  (expected {expected_cat})")
        assert cat == expected_cat, f"wrong category: {cat} != {expected_cat}"

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # All error cases return (None, str)
    for label, (c, e) in [
        ("file not found",    safe_load_config("outputs/nonexistent.json")),
        ("invalid json",      safe_load_config(bad_json)),
        ("missing field",     safe_load_config(bad_cfg_path)),
        ("bad program",       safe_run_pipeline(bad_prog_cfg, verbose=False)),
    ]:
        assert c is None,           f"{label}: config must be None on error"
        assert isinstance(e, str),  f"{label}: error must be a string"
        assert "ERROR" in e,        f"{label}: error string must contain 'ERROR'"
    print("  PASS — all error cases return (None, error_string)")

    # Error strings contain 'ERROR' keyword
    assert "CONFIG ERROR"  in safe_load_config("outputs/nonexistent.json")[1]
    assert "RUNTIME ERROR" in safe_run_pipeline(bad_prog_cfg, verbose=False)[1]
    print("  PASS — error strings have correct category prefix")

    # classify_error maps all 4 cases correctly
    for exc, expected_cat in cases:
        cat, _ = classify_error(exc)
        assert cat == expected_cat
    print("  PASS — classify_error maps all exception types correctly")
