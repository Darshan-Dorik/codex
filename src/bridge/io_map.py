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

PROGRAM SCOPING
---------------
A symbol has no fixed meaning in this codebase. X1 is the FAULT SENSOR
in programs/motor_start.st and the POSITION SENSOR in
programs/shuttle_control.st:

    motor_start.st      X0 start, X1 fault,    Y0 motor
    shuttle_control.st  X0 run,   X1 position, X2 jam, Y0 motor,
                                                       Y1 position lamp

So an IO map is scoped to the ST program whose symbol semantics it
encodes, and a trace is ambiguous without knowing which program
produced it — "X1=True" alone does not say whether the machine
faulted or the shuttle reached position. Diffing a trace from one
program against a map for the other silently mislabels every message
in the report.

Use io_map_for_program() to select by program, and
require_program_match() wherever a map meets a trace.
"""


class IOMap:
    """
    Manages symbolic ↔ human-readable signal mappings.

    An IOMap carries the ST program it was written for. A map with
    program=None is UNSCOPED: usable, but it cannot be checked against
    a trace, so nothing stops it mislabelling one.
    """

    def __init__(self, mapping=None, program=None):
        """
        Args:
            mapping : dict — initial mapping dict (optional)
            program : str | None — ST program these symbols belong to
        """
        self._map = dict(mapping) if mapping else {}
        self.program = program

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

    def to_manifest(self):
        """
        Return the mapping WITH its program scope, for persistence.

        to_dict() is the bare symbol table and says nothing about which
        program's semantics it encodes; a stored map without that is
        the ambiguity this module exists to prevent.
        """
        return {"program": self.program, "signals": dict(self._map)}


# ---------------------------------------------------------------------------
# Program-scoped IO maps
# ---------------------------------------------------------------------------

MOTOR_START_PROGRAM     = "programs/motor_start.st"
SHUTTLE_CONTROL_PROGRAM = "programs/shuttle_control.st"


def make_motor_start_io_map():
    """
    IO map for programs/motor_start.st.

    X0 start, X1 FAULT sensor, Y0 motor. Note X1: in
    shuttle_control.st the same symbol is the position sensor.
    """
    m = IOMap(program=MOTOR_START_PROGRAM)

    m.add("X0", "Start Button", "input",  "bool",
          "Operator start command")
    m.add("X1", "Fault Sensor", "input",  "bool",
          "Fault / emergency stop input — motor drops out while active")

    m.add("Y0", "Main Motor",   "output", "bool",
          "Main drive motor enable")

    return m


def make_shuttle_io_map():
    """
    IO map for programs/shuttle_control.st.

    X0 run, X1 POSITION sensor, X2 jam, Y0 motor, Y1 position lamp.
    Note X1: in motor_start.st the same symbol is the fault sensor.

    This is the map the twin actually drives — loom_twin models a
    position sensor and a jam condition, and has no fault sensor at
    all, so a trace captured from the twin is shuttle_control-scoped.
    """
    m = IOMap(program=SHUTTLE_CONTROL_PROGRAM)

    m.add("X0", "Run Command",        "input",  "bool",
          "Shuttle run command")
    m.add("X1", "Position Sensor",    "input",  "bool",
          "Shuttle position threshold sensor")
    m.add("X2", "Jam Sensor",         "input",  "bool",
          "Shuttle jam detection sensor — motor drops out while active")

    m.add("Y0", "Shuttle Motor",      "output", "bool",
          "Shuttle drive motor enable")
    m.add("Y1", "Position Indicator", "output", "bool",
          "Position reached indicator lamp")

    return m


PROGRAM_IO_MAPS = {
    MOTOR_START_PROGRAM:     make_motor_start_io_map,
    SHUTTLE_CONTROL_PROGRAM: make_shuttle_io_map,
}


def io_map_for_program(program):
    """
    Return the IO map scoped to an ST program.

    Args:
        program : str — program path, e.g. "programs/shuttle_control.st".
                  Matched on basename too, so "shuttle_control.st" works.

    Raises:
        KeyError — unknown program. Guessing a map for an unrecognised
        program is exactly the mislabelling this module prevents.
    """
    if program in PROGRAM_IO_MAPS:
        return PROGRAM_IO_MAPS[program]()

    import os
    base = os.path.basename(program or "")
    for known, factory in PROGRAM_IO_MAPS.items():
        if os.path.basename(known) == base:
            return factory()

    raise KeyError(
        f"no IO map registered for program {program!r}. Known programs: "
        f"{sorted(PROGRAM_IO_MAPS)}. Add one rather than reusing a map "
        f"from another program — symbol meanings are not shared."
    )


def require_program_match(io_map, program, consumer):
    """
    Check an IO map against the program a trace declares.

    Returns:
        [str, ...] — warnings (empty when the match is clean).

    Raises:
        ValueError — the map is scoped to a DIFFERENT program than the
        trace. Every label in the resulting report would be wrong, and
        wrong labels are worse than missing ones because they read as
        authoritative.
    """
    warnings = []

    if program is None:
        if io_map.program is not None:
            warnings.append(
                f"{consumer}: trace declares no program; labelling it "
                f"with the {io_map.program} map is unverified"
            )
        else:
            warnings.append(
                f"{consumer}: neither the trace nor the IO map declares "
                f"a program — symbol meanings are unverified"
            )
        return warnings

    if io_map.program is None:
        warnings.append(
            f"{consumer}: trace declares program {program}, but the IO "
            f"map is unscoped — labels are unverified"
        )
        return warnings

    import os
    if os.path.basename(io_map.program) != os.path.basename(program):
        raise ValueError(
            f"{consumer}: IO map is scoped to {io_map.program} but the "
            f"trace declares {program}. Symbol meanings differ between "
            f"programs (X1 is the fault sensor in motor_start.st and "
            f"the position sensor in shuttle_control.st), so every "
            f"label in this report would be wrong."
        )

    return warnings


# ---------------------------------------------------------------------------
# Legacy unscoped map
# ---------------------------------------------------------------------------

def make_loom_io_map():
    """
    Legacy combined loom IO map. UNSCOPED — prefer the program-scoped
    maps above.

    This map predates program scoping and matches neither ST program
    exactly: it takes X1="Fault Sensor" from motor_start.st while
    placing the position sensor on X3, which no program uses.
    shuttle_control.st puts the position sensor on X1, so this map
    mislabels every shuttle_control trace at X1.

    Retained because existing call sites default to it. New code should
    use io_map_for_program().

    Returns:
        IOMap instance with program=None
    """
    m = IOMap(program=None)

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

    # -------------------------------------------------------
    # Program scoping
    # -------------------------------------------------------
    print("\n" + "=" * 60)
    print("Program-scoped IO maps")
    print("=" * 60)

    ms = make_motor_start_io_map()
    sc = make_shuttle_io_map()

    print("\nThe X1 collision, made explicit:")
    print(f"  {MOTOR_START_PROGRAM:34} X1 → {ms.name('X1')}")
    print(f"  {SHUTTLE_CONTROL_PROGRAM:34} X1 → {sc.name('X1')}")

    print("\nLookup by program:")
    for p in (MOTOR_START_PROGRAM, "shuttle_control.st"):
        got = io_map_for_program(p)
        print(f"  {p:34} → program={got.program}")

    unknown_err = None
    try:
        io_map_for_program("programs/nonexistent.st")
    except KeyError as exc:
        unknown_err = str(exc)
    print(f"\nUnknown program rejected: {unknown_err[:60]}...")

    print("\nMap/trace program agreement:")
    ok_warnings = require_program_match(sc, SHUTTLE_CONTROL_PROGRAM, "test")
    print(f"  matching        → {len(ok_warnings)} warning(s)")

    unscoped_warnings = require_program_match(make_loom_io_map(),
                                              SHUTTLE_CONTROL_PROGRAM, "test")
    print(f"  unscoped map    → {unscoped_warnings[0]}")

    no_prog_warnings = require_program_match(sc, None, "test")
    print(f"  trace w/o prog  → {no_prog_warnings[0]}")

    mismatch_err = None
    try:
        require_program_match(ms, SHUTTLE_CONTROL_PROGRAM, "test")
    except ValueError as exc:
        mismatch_err = str(exc)
    print(f"  wrong program   → raised")

    # -------------------------------------------------------
    print("\n--- Program scoping assertions ---")

    assert ms.name("X1") == "Fault Sensor",    "motor_start X1 is fault"
    assert sc.name("X1") == "Position Sensor", "shuttle X1 is position"
    assert ms.name("X1") != sc.name("X1"), \
        "the collision this module exists for must be real"
    print("  PASS — X1 means different things per program, and the maps "
          "say so")

    assert ms.program == MOTOR_START_PROGRAM
    assert sc.program == SHUTTLE_CONTROL_PROGRAM
    assert make_loom_io_map().program is None, "legacy map is unscoped"
    print("  PASS — scoped maps declare their program; legacy is unscoped")

    assert io_map_for_program("shuttle_control.st").program == \
        SHUTTLE_CONTROL_PROGRAM, "basename lookup works"
    assert unknown_err is not None and "no IO map registered" in unknown_err
    print("  PASS — lookup by path or basename; unknown program refused")

    assert ok_warnings == [],           "matching program → no warnings"
    assert len(unscoped_warnings) == 1, "unscoped map → warning"
    assert len(no_prog_warnings) == 1,  "trace without program → warning"
    assert mismatch_err is not None,    "wrong program must raise"
    assert "every label in this report would be wrong" in mismatch_err
    print("  PASS — match clean, unscoped/undeclared warn, mismatch raises")

    manifest = sc.to_manifest()
    assert manifest["program"] == SHUTTLE_CONTROL_PROGRAM
    assert manifest["signals"]["X1"]["name"] == "Position Sensor"
    assert sc.to_dict() == manifest["signals"], "to_dict stays bare"
    print("  PASS — to_manifest carries program, to_dict unchanged")
