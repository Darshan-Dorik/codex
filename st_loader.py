"""
st_loader.py — ST File Loader

Loads Structured Text programs from .st files and feeds them into the parser.
"""

import os


def load_st_file(filepath):
    """
    Load a Structured Text program from a file.

    Args:
        filepath: str — path to .st file (relative or absolute)

    Returns:
        str — the raw ST code as a string

    Raises:
        FileNotFoundError if the file doesn't exist
        IOError if the file can't be read
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"ST file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import json
    from st_parser import parse_st

    print("=" * 60)
    print("Phase 5 - Step 1: ST File Loader")
    print("=" * 60)

    # --- Test 1: Load motor_start.st ---
    file1 = "programs/motor_start.st"
    print(f"\nTest 1 — Loading: {file1}")

    st_code_1 = load_st_file(file1)
    print(f"  Raw ST code ({len(st_code_1)} chars):")
    print("  " + "-" * 50)
    print(st_code_1.strip())
    print("  " + "-" * 50)

    parsed_1 = parse_st(st_code_1)
    print(f"\n  Parsed structure:")
    print(json.dumps(parsed_1, indent=2))

    # --- Test 2: Load shuttle_control.st ---
    file2 = "programs/shuttle_control.st"
    print(f"\nTest 2 — Loading: {file2}")

    st_code_2 = load_st_file(file2)
    print(f"  Raw ST code ({len(st_code_2)} chars):")
    print("  " + "-" * 50)
    print(st_code_2.strip())
    print("  " + "-" * 50)

    parsed_2 = parse_st(st_code_2)
    print(f"\n  Parsed structure:")
    print(json.dumps(parsed_2, indent=2))

    # --- Assertions ---
    print("\n--- Assertions ---")

    assert len(parsed_1) == 1,                      "motor_start.st: expected 1 IF block"
    assert parsed_1[0]["type"] == "if_else",        "motor_start.st: type must be if_else"
    assert len(parsed_1[0]["then_body"]) == 1,      "motor_start.st: 1 statement in THEN"
    assert len(parsed_1[0]["else_body"]) == 1,      "motor_start.st: 1 statement in ELSE"
    print("  PASS — motor_start.st: structure correct")

    assert len(parsed_2) == 2,                      "shuttle_control.st: expected 2 IF blocks"
    assert parsed_2[0]["type"] == "if_else",        "shuttle_control.st: block 1 type"
    assert parsed_2[1]["type"] == "if_else",        "shuttle_control.st: block 2 type"
    print("  PASS — shuttle_control.st: structure correct (2 IF blocks)")

    # --- Test 3: Nonexistent file ---
    print("\nTest 3 — Nonexistent file handling:")
    try:
        load_st_file("programs/nonexistent.st")
        print("  FAIL — should have raised FileNotFoundError")
    except FileNotFoundError as e:
        print(f"  PASS — FileNotFoundError raised: {e}")
