"""
real_trace.py — Real Trace Data Structure

Defines the structure for real machine signal logs.
This is READ-ONLY data captured from a real PLC or machine.

Real trace format:
[
  {
    "time":    int,          # timestamp in ms (relative or absolute)
    "signals": {str: bool}   # all signals (inputs + outputs) at this time
  },
  ...
]

Unlike simulation traces (which separate inputs/outputs), real traces
combine all signals into one dict since we're just observing the machine.

SAFETY: This module only defines data structures and validation.
It does NOT connect to any real hardware.
"""

import json


def validate_real_trace(trace):
    """
    Validate that a real trace list conforms to the expected structure.

    Args:
        trace : list — real trace entries

    Returns:
        {
          "valid":  bool,
          "errors": [str, ...]   # validation error messages
        }
    """
    errors = []

    if not isinstance(trace, list):
        errors.append("trace must be a list")
        return {"valid": False, "errors": errors}

    for i, entry in enumerate(trace):
        if not isinstance(entry, dict):
            errors.append(f"entry {i}: must be a dict")
            continue

        if "time" not in entry:
            errors.append(f"entry {i}: missing 'time' key")
        elif not isinstance(entry["time"], int):
            errors.append(f"entry {i}: 'time' must be an int")

        if "signals" not in entry:
            errors.append(f"entry {i}: missing 'signals' key")
        elif not isinstance(entry["signals"], dict):
            errors.append(f"entry {i}: 'signals' must be a dict")

    return {
        "valid":  len(errors) == 0,
        "errors": errors
    }


def save_real_trace(trace, filepath="real_trace.json"):
    """Save a real trace to a JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2)


def load_real_trace(filepath="real_trace.json"):
    """Load a real trace from disk."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def create_mock_real_trace(sim_trace, noise_fn=None):
    """
    Create a mock real trace from a simulation trace for testing.

    Combines inputs + outputs into a single 'signals' dict.
    Optionally applies a noise function to simulate real-world variance.

    Args:
        sim_trace : list — simulation trace from export_sim_trace()
        noise_fn  : callable(signals, time) -> signals — optional noise injector

    Returns:
        list — real trace entries
    """
    real_trace = []

    for entry in sim_trace:
        signals = {}
        signals.update(entry.get("inputs", {}))
        signals.update(entry.get("outputs", {}))

        if noise_fn:
            signals = noise_fn(signals, entry["time"])

        real_trace.append({
            "time":    entry["time"],
            "signals": signals
        })

    return real_trace


if __name__ == "__main__":
    import os

    print("=" * 60)
    print("Phase 7 - Step 3: Real Trace Data Structure")
    print("=" * 60)

    # --- Test 1: create mock real trace from sim trace ---
    print("\nTest 1 — Create mock real trace:")

    # Load the sim trace from Step 2
    sim_trace_path = "outputs/sim_trace.json"
    if not os.path.exists(sim_trace_path):
        print(f"  {sim_trace_path} not found — run sim_trace.py first")
        exit(1)

    from sim_trace import load_sim_trace
    sim_trace = load_sim_trace(sim_trace_path)

    # Create mock real trace (no noise)
    real_trace = create_mock_real_trace(sim_trace)

    print(f"  Sim trace entries  : {len(sim_trace)}")
    print(f"  Real trace entries : {len(real_trace)}")
    print("\n  Sample real trace entry:")
    print(json.dumps(real_trace[3], indent=2))

    # --- Test 2: validate structure ---
    print("\nTest 2 — Validate real trace structure:")
    validation = validate_real_trace(real_trace)
    print(f"  valid  : {validation['valid']}")
    print(f"  errors : {validation['errors']}")

    # --- Test 3: inject noise (flip Y0 at t=300ms) ---
    print("\nTest 3 — Mock real trace with noise:")

    def inject_noise(signals, time):
        """Flip Y0 at t=300ms to simulate a mismatch."""
        if time == 300 and "Y0" in signals:
            signals = dict(signals)
            signals["Y0"] = not signals["Y0"]
        return signals

    noisy_trace = create_mock_real_trace(sim_trace, noise_fn=inject_noise)
    t300_sim  = next(e for e in sim_trace if e["time"] == 300)
    t300_real = next(e for e in noisy_trace if e["time"] == 300)
    print(f"  t=300ms sim  Y0 : {t300_sim['outputs']['Y0']}")
    print(f"  t=300ms real Y0 : {t300_real['signals']['Y0']}")

    # --- Test 4: save and reload ---
    print("\nTest 4 — Save and reload:")
    output_path = "outputs/real_trace_mock.json"
    save_real_trace(real_trace, output_path)
    loaded = load_real_trace(output_path)
    print(f"  Saved to: {output_path}")
    print(f"  Reloaded {len(loaded)} entries")

    # --- Test 5: invalid trace ---
    print("\nTest 5 — Validate invalid trace:")
    invalid = [
        {"time": 100, "signals": {"X0": True}},
        {"signals": {"X0": False}},              # missing 'time'
        {"time": "300", "signals": {"X0": True}} # wrong type
    ]
    validation_bad = validate_real_trace(invalid)
    print(f"  valid  : {validation_bad['valid']}")
    print(f"  errors : {validation_bad['errors']}")

    # --- Assertions ---
    print("\n--- Assertions ---")

    assert len(real_trace) == len(sim_trace),   "same tick count"
    print("  PASS — real trace has same tick count as sim trace")

    assert validation["valid"] is True,         "clean trace must be valid"
    assert validation["errors"] == [],          "no errors"
    print("  PASS — clean real trace validates correctly")

    assert t300_sim["outputs"]["Y0"] is True,   "sim Y0=True at t=300"
    assert t300_real["signals"]["Y0"] is False, "noisy real Y0=False at t=300"
    print("  PASS — noise injection works (Y0 flipped at t=300)")

    assert loaded == real_trace,                "round-trip identical"
    print("  PASS — JSON round-trip identical")

    assert validation_bad["valid"] is False,    "invalid trace detected"
    assert len(validation_bad["errors"]) >= 2,  "at least 2 errors"
    print(f"  PASS — invalid trace rejected ({len(validation_bad['errors'])} errors)")
