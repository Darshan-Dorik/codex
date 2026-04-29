"""
io_map.py — IO Mapping Layer

Defines a mapping between PLC symbolic variable names (X0, Y0, etc.)
and their human-readable descriptions, signal types, and units.

This layer is READ-ONLY with respect to the real machine.
It is used purely for labelling, reporting, and trace interpretation.

Mapping structure:
{
  "<symbol>": {
    "name":      str,   # human-readable signal name
    "type":      str,   # "input" | "output" | "internal"
    "unit":      str,   # optional: "bool", "int", "float"
    "description": str  # optional: longer description
  }
}
"""


class IOMap:
    """
    Manages symbolic ↔ human-readable signal mappings.
    """

    def __init__(self, mapping=None):
        """
        Args:
            mapping : dict — initial mapping dict (optional)
        """
        self._map = dict(mapping) if mapping else {}

    def add(self, symbol, name, signal_type="input", unit="bool",
            description=""):
        """Add or update a single signal mapping."""
        self._map[symbol] = {
            "name":        name,
            "type":        signal_type,
            "unit":        unit,
            "description": description
        }

    def get(self, symbol):
        """
        Return the mapping entry for a symbol, or a default if not found.
        """
        return self._map.get(symbol, {
            "name":        symbol,   # fall back to symbol itself
            "type":        "unknown",
            "unit":        "bool",
            "description": ""
        })

    def name(self, symbol):
        """Return just the human-readable name for a symbol."""
        return self.get(symbol)["name"]

    def symbol_for_name(self, name):
        """
        Reverse lookup: find the symbol for a given human-readable name.
        Returns None if not found.
        """
        for sym, entry in self._map.items():
            if entry["name"] == name:
                return sym
        return None

    def translate_dict(self, signal_dict):
        """
        Translate a {symbol: value} dict to {human_name: value}.

        Args:
            signal_dict : dict — e.g. {"X0": True, "Y0": False}

        Returns:
            dict — e.g. {"Start Button": True, "Main Motor": False}
        """
        return {self.name(sym): val for sym, val in signal_dict.items()}

    def translate_timeline(self, timeline):
        """
        Translate all inputs/outputs in a timeline to human-readable names.

        Args:
            timeline : list of {"time": int, "inputs": {...}, "outputs": {...}}

        Returns:
            list of {"time": int, "inputs": {...}, "outputs": {...}}
            with all signal keys replaced by human-readable names
        """
        result = []
        for entry in timeline:
            translated = {"time": entry["time"]}
            if "inputs" in entry:
                translated["inputs"] = self.translate_dict(entry["inputs"])
            if "outputs" in entry:
                translated["outputs"] = self.translate_dict(entry["outputs"])
            if "signals" in entry:
                translated["signals"] = self.translate_dict(entry["signals"])
            result.append(translated)
        return result

    def all_symbols(self):
        """Return list of all mapped symbols."""
        return list(self._map.keys())

    def inputs(self):
        """Return list of symbols mapped as inputs."""
        return [s for s, e in self._map.items() if e["type"] == "input"]

    def outputs(self):
        """Return list of symbols mapped as outputs."""
        return [s for s, e in self._map.items() if e["type"] == "output"]

    def to_dict(self):
        """Return the full mapping as a plain dict (JSON-serialisable)."""
        return dict(self._map)


# ---------------------------------------------------------------------------
# Default loom IO map — used across Phase 7 steps
# ---------------------------------------------------------------------------

def make_loom_io_map():
    """
    Create the standard IO map for the circular loom PLC program.

    Returns:
        IOMap instance
    """
    m = IOMap()

    # Inputs
    m.add("X0", "Start Button",       "input",  "bool",
          "Operator start command")
    m.add("X1", "Fault Sensor",       "input",  "bool",
          "General fault / emergency stop input")
    m.add("X2", "Jam Sensor",         "input",  "bool",
          "Shuttle jam detection sensor")
    m.add("X3", "Position Sensor",    "input",  "bool",
          "Shuttle position threshold sensor")

    # Outputs
    m.add("Y0", "Main Motor",         "output", "bool",
          "Main drive motor enable")
    m.add("Y1", "Position Indicator", "output", "bool",
          "Position reached indicator lamp")
    m.add("Y2", "Fault Lamp",         "output", "bool",
          "Fault indicator lamp")

    return m


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("Phase 7 - Step 1: IO Mapping Layer")
    print("=" * 60)

    io = make_loom_io_map()

    # --- Test 1: name lookup ---
    print("\nTest 1 — Symbol → Name lookup:")
    for sym in ["X0", "X1", "X2", "Y0", "Y1", "Y2", "X9"]:
        print(f"  {sym:4} → {io.name(sym)}")

    # --- Test 2: reverse lookup ---
    print("\nTest 2 — Name → Symbol reverse lookup:")
    for name in ["Start Button", "Main Motor", "Unknown Signal"]:
        sym = io.symbol_for_name(name)
        print(f"  '{name}' → {sym}")

    # --- Test 3: translate dict ---
    print("\nTest 3 — Translate signal dict:")
    raw = {"X0": True, "X1": False, "Y0": True, "Y2": False}
    translated = io.translate_dict(raw)
    print(f"  Raw      : {raw}")
    print(f"  Readable : {translated}")

    # --- Test 4: translate timeline ---
    print("\nTest 4 — Translate timeline:")
    timeline = [
        {"time": 100, "inputs": {"X0": True, "X1": False},
         "outputs": {"Y0": True}},
        {"time": 200, "inputs": {"X0": True, "X1": True},
         "outputs": {"Y0": False}},
    ]
    readable = io.translate_timeline(timeline)
    print(json.dumps(readable, indent=2))

    # --- Test 5: list inputs / outputs ---
    print("\nTest 5 — Inputs and Outputs:")
    print(f"  Inputs  : {io.inputs()}")
    print(f"  Outputs : {io.outputs()}")

    # --- Test 6: full map as dict ---
    print("\nTest 6 — Full mapping (JSON):")
    print(json.dumps(io.to_dict(), indent=2))

    # --- Assertions ---
    print("\n--- Assertions ---")

    assert io.name("X0") == "Start Button",       "X0 name"
    assert io.name("Y0") == "Main Motor",          "Y0 name"
    assert io.name("X9") == "X9",                  "unknown falls back to symbol"
    print("  PASS — name lookups correct (including unknown fallback)")

    assert io.symbol_for_name("Main Motor") == "Y0"
    assert io.symbol_for_name("Unknown") is None
    print("  PASS — reverse lookup correct")

    assert translated["Start Button"] is True
    assert translated["Main Motor"]   is True
    print("  PASS — translate_dict correct")

    assert readable[0]["inputs"]["Start Button"] is True
    assert readable[1]["outputs"]["Main Motor"]  is False
    print("  PASS — translate_timeline correct")

    assert "X0" in io.inputs()
    assert "Y0" in io.outputs()
    assert "X0" not in io.outputs()
    print("  PASS — inputs/outputs lists correct")
