"""
tag_map.py — Declarative Register Map for the Twin Shim

Maps TwinRuntime snapshot fields onto Modbus register addresses.

There is ONE tag map and every transport reads through it, so a value
polled over Modbus and a value read over HTTP come from the same field
of the same scan. Two transports with two hand-written mappings is how
a bench rig starts teaching the collector something the real machine
will not repeat.

Every tag carries PROVENANCE — which snapshot field it came from,
which PLC symbol it corresponds to, its scale and its unit. That is
the same discipline the platform brief demands of a real acquisition
tag, and it is cheap to honour here where the source is known exactly.

PROGRAM SCOPE
-------------
The bit assignments in the input/output words are meaningless without
the ST program: X1 is the position sensor under shuttle_control.st and
the fault sensor under motor_start.st. The map therefore declares its
program, and a trace recorded through it inherits that provenance.

ADDRESSING
----------
All values live in the READ-ONLY object model. Modbus has no write
function code for input registers, so read-only is a property of the
address space rather than a rule the server is trusting itself to
follow. FC3 (holding registers) is served as an alias of FC4 because
real drives expose their data there — the Delta MS300 profile in the
platform brief reads 0x2103 as a holding register — so a collector
written against real hardware works here unchanged.

Booleans are packed into bitfield words rather than exposed as coils
or discrete inputs, because FC1/FC2 are not implemented either.

WRAPPING
--------
scan_time_ms is a 32-bit millisecond counter and wraps after ~49.7
days. A collector that runs longer than that must handle the wrap;
scan_count (16-bit) wraps far sooner and exists to detect MISSED
POLLS, not to measure time.
"""

PROTOCOL_VERSION = 1

# Motor state enum, exposed as a register value.
MOTOR_STATES = ("STOPPED", "STARTING", "RUNNING", "STOPPING")


class Tag:
    """One entry in the register map."""

    def __init__(self, address, name, kind, source, unit="",
                 scale=1.0, bits=None, note=""):
        """
        Args:
            address : int   — starting register address
            name    : str   — tag name
            kind    : str   — "uint16" | "uint32" | "bitfield" | "enum"
            source  : callable(snapshot) -> raw value
            unit    : str   — engineering unit
            scale   : float — engineering value = raw * scale
            bits    : dict  — {bit_index: symbol} for bitfield tags
            note    : str   — provenance / interpretation note
        """
        self.address = address
        self.name    = name
        self.kind    = kind
        self.source  = source
        self.unit    = unit
        self.scale   = scale
        self.bits    = bits or {}
        self.note    = note

    @property
    def word_count(self):
        return 2 if self.kind == "uint32" else 1

    def read(self, snapshot):
        """Return this tag's register words for a snapshot."""
        value = self.source(snapshot)

        if self.kind == "uint32":
            v = int(value) & 0xFFFFFFFF
            return [(v >> 16) & 0xFFFF, v & 0xFFFF]

        if self.kind == "bitfield":
            word = 0
            for bit, symbol in self.bits.items():
                if value.get(symbol):
                    word |= (1 << bit)
            return [word & 0xFFFF]

        if self.kind == "enum":
            return [MOTOR_STATES.index(value) if value in MOTOR_STATES
                    else 0xFFFF]

        # uint16, with scale applied on the way out
        raw = int(round(float(value) / self.scale)) if self.scale != 1.0 \
            else int(value)
        return [max(0, min(raw, 0xFFFF))]

    def provenance(self):
        return {
            "address": self.address,
            "name":    self.name,
            "kind":    self.kind,
            "unit":    self.unit,
            "scale":   self.scale,
            "bits":    dict(self.bits),
            "note":    self.note,
            "words":   self.word_count,
        }


class TagMap:
    """The register image for one runtime."""

    def __init__(self, tags, program=None):
        self.tags    = sorted(tags, key=lambda t: t.address)
        self.program = program

        seen = {}
        for tag in self.tags:
            for offset in range(tag.word_count):
                addr = tag.address + offset
                if addr in seen:
                    raise ValueError(
                        f"register {addr} claimed by both {seen[addr]!r} "
                        f"and {tag.name!r}")
                seen[addr] = tag.name
            if not tag.note:
                raise ValueError(
                    f"tag {tag.name!r} has no provenance note; every tag "
                    f"must say where its value came from")

        self.size = max(seen) + 1 if seen else 0
        self._addr_owner = seen

    def render(self, snapshot):
        """
        Build the full register image for a snapshot.

        Unclaimed addresses read 0 rather than erroring, matching how a
        real device answers a read of a gap in its map.
        """
        image = [0] * self.size
        for tag in self.tags:
            words = tag.read(snapshot)
            for offset, word in enumerate(words):
                image[tag.address + offset] = word & 0xFFFF
        return image

    def describe(self):
        """Register map as data — for docs, tests, and the platform repo."""
        return {
            "program":          self.program,
            "protocol_version": PROTOCOL_VERSION,
            "size":             self.size,
            "tags":             [t.provenance() for t in self.tags],
        }

    def decode(self, image, base=0):
        """
        Interpret a register image back into engineering values.

        The inverse of render(), so a test can prove the round trip
        rather than asserting the encoder against itself.

        A PARTIAL image is fine — a collector reading registers 0..1
        gets back only the tags those words fully cover, rather than
        an error or, worse, a value decoded from words that were never
        read. Tags that do not fit are simply absent from the result.

        Args:
            image : list[int] — register words
            base  : int — address of image[0], for reads that do not
                    start at register 0
        """
        out = {}
        for tag in self.tags:
            start = tag.address - base
            if start < 0 or start + tag.word_count > len(image):
                continue
            words = image[start:start + tag.word_count]
            if tag.kind == "uint32":
                out[tag.name] = (words[0] << 16) | words[1]
            elif tag.kind == "bitfield":
                out[tag.name] = {sym: bool(words[0] & (1 << bit))
                                 for bit, sym in sorted(tag.bits.items())}
            elif tag.kind == "enum":
                idx = words[0]
                out[tag.name] = (MOTOR_STATES[idx]
                                 if idx < len(MOTOR_STATES) else "UNKNOWN")
            else:
                out[tag.name] = (words[0] * tag.scale if tag.scale != 1.0
                                 else words[0])
        return out


# ---------------------------------------------------------------------------
# Signals — the canonical, transport-neutral definitions
# ---------------------------------------------------------------------------
#
# ONE SOURCE, TWO FACES. A signal is defined once here; the Modbus
# register map and the OPC UA NodeSet are both projections of it.
# Defining a signal twice is how a bench rig ends up telling two
# collectors two different stories about the same machine.
#
# The hierarchy is line -> unit -> measure, deliberately matching the
# topic namespace from the platform brief:
#
#     <enterprise>/<site>/<area>/<line>/<unit>/<measure>
#     jpgroup/ankleshwar/weaving/loom-01/shuttle/position
#
# EUROMAP 84 / OPC 40084 ALIGNMENT — NOT DONE, AND DELIBERATELY SO.
# The 40084 series has no circular loom part, so mapping onto it now
# would mean extending a standard before ever conforming to one. This
# uses its own namespace. The hierarchy is shaped so the later mapping
# is mechanical rather than a re-model: units correspond to what 40084
# calls components, measures to their variables.


class ModbusPlacement:
    """Where a signal lands in the register map."""

    def __init__(self, address, words=1, bit=None, word_name=None,
                 encoding="uint16"):
        self.address   = address
        self.words     = words
        self.bit       = bit
        self.word_name = word_name    # for signals packed into one word
        self.encoding  = encoding


class Signal:
    """
    One atomic measured value.

    Carries what BOTH transports need — identity, hierarchy, datatype,
    engineering unit, provenance — plus a Modbus placement. The OPC UA
    projection ignores the placement; the Modbus projection ignores the
    hierarchy. Neither redefines the signal.
    """

    def __init__(self, measure, unit_name, datatype, source,
                 symbol=None, eng_unit="", scale=1.0, note="",
                 enum_values=None, modbus=None):
        self.measure     = measure      # canonical name, OPC UA BrowseName
        self.unit_name   = unit_name    # machine unit: drive/shuttle/controller
        self.datatype    = datatype     # OPC UA built-in type name
        self.source      = source       # callable(snapshot) -> value
        self.symbol      = symbol       # PLC symbol (X0/Y0), if any
        self.eng_unit    = eng_unit
        self.scale       = scale
        self.note        = note
        self.enum_values = enum_values
        self.modbus      = modbus

    def value(self, snapshot):
        """Engineering value — what OPC UA exposes."""
        return self.source(snapshot)


class SignalSet:
    """A line's signals, plus where the line sits in the namespace."""

    def __init__(self, signals, program=None, enterprise="jpgroup",
                 site="ankleshwar", area="weaving", line="loom-01",
                 namespace_uri="http://jpgroup.example/UA/LoomTwin/"):
        self.signals       = list(signals)
        self.program       = program
        self.enterprise    = enterprise
        self.site          = site
        self.area          = area
        self.line          = line
        self.namespace_uri = namespace_uri

        for sig in self.signals:
            if not sig.note:
                raise ValueError(
                    f"signal {sig.measure!r} has no provenance note")

    def topic(self, signal):
        """The signal's topic path, per the brief's namespace."""
        return "/".join((self.enterprise, self.site, self.area, self.line,
                         signal.unit_name, signal.measure))

    def units(self):
        """Machine units, in first-appearance order."""
        seen = []
        for sig in self.signals:
            if sig.unit_name not in seen:
                seen.append(sig.unit_name)
        return seen

    def by_unit(self, unit_name):
        return [s for s in self.signals if s.unit_name == unit_name]

    def by_measure(self, measure):
        for s in self.signals:
            if s.measure == measure:
                return s
        raise KeyError(measure)


def make_twin_signals(program="programs/shuttle_control.st"):
    """
    The twin's signals — the single definition both faces project from.

    Symbols are PROGRAM-SCOPED: X1 is the position sensor under
    shuttle_control.st and the fault sensor under motor_start.st, so
    the set records which program it describes.
    """
    return SignalSet([
        Signal("scan_time_ms", "controller", "UInt32",
               lambda s: s["time"], eng_unit="ms",
               modbus=ModbusPlacement(0, words=2, encoding="uint32"),
               note="TwinRuntime.t_ms — PLC scan timestamp. Record this "
                    "as the trace timestamp (TS_SCAN) so traces align "
                    "exactly. Wraps after ~49.7 days."),

        Signal("scan_count", "controller", "UInt16",
               lambda s: s["scan_count"] & 0xFFFF, eng_unit="count",
               modbus=ModbusPlacement(6),
               note="PLC scans since start; wraps at 65535. Exists so a "
                    "collector can detect MISSED POLLS, not to measure "
                    "time"),

        Signal("protocol_version", "controller", "UInt16",
               lambda s: PROTOCOL_VERSION,
               modbus=ModbusPlacement(7),
               note="Shim register-map version; bump on any layout change"),

        Signal("run_command", "controller", "Boolean",
               lambda s: bool(s["sensors"].get("X0")), symbol="X0",
               modbus=ModbusPlacement(8, bit=0, word_name="plc_inputs"),
               note="PLC input X0 — the operator's run command. Stays "
                    "asserted during a jam; nothing about a jam "
                    "withdraws it"),

        Signal("motor_state", "drive", "String",
               lambda s: s["motor_state"], enum_values=MOTOR_STATES,
               modbus=ModbusPlacement(3, encoding="enum"),
               note="MotorStateMachine.state: "
                    "0=STOPPED 1=STARTING 2=RUNNING 3=STOPPING"),

        Signal("motor_contactor", "drive", "Boolean",
               lambda s: bool(s["outputs"].get("Y0")), symbol="Y0",
               modbus=ModbusPlacement(9, bit=0, word_name="plc_outputs"),
               note="PLC output Y0 — shuttle motor enable. Exists only "
                    "because the PLC is in the loop"),

        Signal("position", "shuttle", "Double",
               lambda s: s["shuttle_position"], eng_unit="deg", scale=0.01,
               modbus=ModbusPlacement(2),
               note="CyclicShuttleModel.position, 0-360 deg. Carried on "
                    "Modbus as x100 in a uint16 (max 35999 fits)"),

        Signal("cycles_completed", "shuttle", "UInt16",
               lambda s: s["cycles_completed"], eng_unit="count",
               modbus=ModbusPlacement(4),
               note="CyclicShuttleModel.cycles_completed; wraps at 65535"),

        Signal("position_sensor", "shuttle", "Boolean",
               lambda s: bool(s["sensors"].get("X1")), symbol="X1",
               modbus=ModbusPlacement(8, bit=1, word_name="plc_inputs"),
               note="PLC input X1 — shuttle position threshold sensor "
                    "under shuttle_control.st. NOTE: X1 is the FAULT "
                    "sensor under motor_start.st"),

        Signal("position_indicator", "shuttle", "Boolean",
               lambda s: bool(s["outputs"].get("Y1")), symbol="Y1",
               modbus=ModbusPlacement(9, bit=1, word_name="plc_outputs"),
               note="PLC output Y1 — position reached indicator lamp"),

        Signal("jam_sensor", "shuttle", "Boolean",
               lambda s: bool(s["sensors"].get("X2")), symbol="X2",
               modbus=ModbusPlacement(8, bit=2, word_name="plc_inputs"),
               note="PLC input X2 — shuttle jam detection sensor"),

        Signal("jam_detected", "shuttle", "Boolean",
               lambda s: bool(s["jam_detected"]),
               modbus=ModbusPlacement(5),
               note="Jam injector state. Mirrors X2, but is the twin's "
                    "own view rather than the PLC input image — they "
                    "differ if the PLC ever samples between edges"),
    ], program=program)


def modbus_tag_map(signal_set):
    """
    Project a SignalSet onto the Modbus register map.

    The layout is a PUBLISHED CONTRACT (see protocol_version), so
    addresses come from each signal's declared placement rather than
    being auto-assigned — auto-assignment would silently re-point every
    deployed collector the moment a signal was reordered.

    Bit-packed signals are grouped into their shared word and keyed by
    PLC SYMBOL, because that is what the trace format and the bridge
    compare on. The OPC UA face keys the same signals by measure name.
    """
    scalars = []
    packed  = {}

    for sig in signal_set.signals:
        if sig.modbus is None:
            continue
        if sig.modbus.bit is None:
            scalars.append(sig)
        else:
            packed.setdefault(
                (sig.modbus.address, sig.modbus.word_name), []).append(sig)

    tags = []

    for sig in scalars:
        placement = sig.modbus
        if placement.encoding == "uint32":
            kind = "uint32"
            source = sig.source
        elif placement.encoding == "enum":
            kind = "enum"
            source = sig.source
        elif sig.datatype == "Boolean":
            kind = "uint16"
            source = (lambda s, _s=sig: 1 if _s.source(s) else 0)
        else:
            kind = "uint16"
            source = sig.source
        tags.append(Tag(placement.address, sig.measure, kind, source,
                        unit=sig.eng_unit, scale=sig.scale,
                        note=sig.note))

    for (address, word_name), sigs in sorted(packed.items()):
        bits = {s.modbus.bit: s.symbol for s in sigs}
        members = ", ".join(f"bit{s.modbus.bit}={s.symbol}:{s.measure}"
                            for s in sorted(sigs, key=lambda x: x.modbus.bit))
        tags.append(Tag(
            address, word_name, "bitfield",
            (lambda s, _sigs=sigs: {
                _x.symbol: bool(_x.source(s)) for _x in _sigs}),
            bits=bits,
            note=(f"Packed PLC image, PROGRAM-SCOPED to "
                  f"{signal_set.program}: {members}")))

    return TagMap(tags, program=signal_set.program)


def make_twin_tag_map(program="programs/shuttle_control.st"):
    """
    The standard register map for a TwinRuntime.

    Now a projection of make_twin_signals() rather than a second
    hand-written definition of the same signals.

    Addresses 0-1 are the load-bearing ones for trace comparison: they
    carry the twin's own SCAN TIME. A collector that records this as
    the trace timestamp produces traces that align against sim traces
    at tolerance 0, because the timestamp IS the scan timestamp. A
    collector that stamps on arrival instead needs a tolerance window
    for no reason — see trace_aligner.TS_SCAN vs TS_ARRIVAL.
    """
    return modbus_tag_map(make_twin_signals(program=program))


if __name__ == "__main__":
    import json
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from twin_runtime import make_runtime

    print("=" * 60)
    print("Phase 11 - Step 6: Shim Tag Map")
    print("=" * 60)

    tm = make_twin_tag_map()

    print(f"\nRegister map ({tm.size} words, program {tm.program}):")
    print(f"  {'addr':>4}  {'name':18} {'kind':9} {'unit':5} {'scale':>6}")
    print("  " + "-" * 52)
    for t in tm.tags:
        span = (f"{t.address}-{t.address + t.word_count - 1}"
                if t.word_count > 1 else str(t.address))
        print(f"  {span:>4}  {t.name:18} {t.kind:9} {t.unit:5} "
              f"{t.scale:>6}")
        if t.bits:
            for bit, sym in sorted(t.bits.items()):
                print(f"        bit {bit} = {sym}")

    # -------------------------------------------------------
    print("\nTest 1 — Render a live snapshot:")
    rt = make_runtime()
    rt.run_until(2000)
    snap  = rt.snapshot()
    image = tm.render(snap)
    print(f"  snapshot t={snap['time']}ms pos={snap['shuttle_position']} "
          f"state={snap['motor_state']}")
    print(f"  registers: {image}")

    # -------------------------------------------------------
    print("\nTest 2 — Decode back to engineering values:")
    decoded = tm.decode(image)
    for k, v in decoded.items():
        print(f"    {k:18} = {v}")

    # -------------------------------------------------------
    print("\nTest 3 — Jam state reaches the registers:")
    rt2 = make_runtime()
    rt2.run_until(12400)          # past the 2-cycle jam trigger
    jam_image   = tm.render(rt2.snapshot())
    jam_decoded = tm.decode(jam_image)
    print(f"    jam_detected = {jam_decoded['jam_detected']}")
    print(f"    plc_inputs   = {jam_decoded['plc_inputs']}")
    print(f"    plc_outputs  = {jam_decoded['plc_outputs']}")

    # -------------------------------------------------------
    print("\nTest 4 — Address collision and missing provenance rejected:")
    collision_err = provenance_err = None
    try:
        TagMap([Tag(0, "a", "uint32", lambda s: 0, note="x"),
                Tag(1, "b", "uint16", lambda s: 0, note="y")])
    except ValueError as exc:
        collision_err = str(exc)
    try:
        TagMap([Tag(0, "no_note", "uint16", lambda s: 0)])
    except ValueError as exc:
        provenance_err = str(exc)
    print(f"    collision : {collision_err}")
    print(f"    provenance: {provenance_err}")

    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert decoded["scan_time_ms"] == snap["time"], \
        "scan time must round-trip exactly — traces depend on it"
    print(f"  PASS — scan_time_ms round-trips exactly "
          f"({decoded['scan_time_ms']}ms)")

    assert abs(decoded["position"] - snap["shuttle_position"]) < 0.01
    print(f"  PASS — position round-trips within scale "
          f"({decoded['position']} deg)")

    assert decoded["motor_state"] == snap["motor_state"]
    assert decoded["plc_inputs"] == {k: bool(v)
                                     for k, v in snap["sensors"].items()}
    assert decoded["plc_outputs"] == {k: bool(v)
                                      for k, v in snap["outputs"].items()}
    print("  PASS — motor_state, plc_inputs and plc_outputs round-trip")

    assert decoded["protocol_version"] == PROTOCOL_VERSION
    print(f"  PASS — protocol_version = {PROTOCOL_VERSION}")

    assert jam_decoded["jam_detected"] == 1
    assert jam_decoded["plc_inputs"]["X2"] is True
    assert jam_decoded["plc_inputs"]["X0"] is True, \
        "X0 stays asserted during a jam"
    assert jam_decoded["plc_outputs"]["Y0"] is False, \
        "Y0 drops during a jam"
    print("  PASS — jam visible in registers: X2 set, X0 still set, "
          "Y0 clear")

    assert all(0 <= w <= 0xFFFF for w in image), \
        "every register must be a 16-bit word"
    print(f"  PASS — all {len(image)} registers within 16 bits")

    assert collision_err is not None and "claimed by both" in collision_err
    assert provenance_err is not None and "provenance" in provenance_err
    print("  PASS — address collisions and provenance-less tags rejected")

    print("\n--- Register map as data ---")
    print(json.dumps(tm.describe(), indent=2)[:400] + " ...")

    # -------------------------------------------------------
    print("\nTest 5 — Partial reads decode only what they cover:")
    partial = tm.render(snap)[0:2]          # a collector reading 0..1
    partial_decoded = tm.decode(partial)
    print(f"    read 0..1 → {partial_decoded}")

    offset = tm.render(snap)[8:10]          # reading 8..9 only
    offset_decoded = tm.decode(offset, base=8)
    print(f"    read 8..9 → {offset_decoded}")

    assert set(partial_decoded) == {"scan_time_ms"}, \
        "a 2-word read covers only scan_time_ms"
    assert partial_decoded["scan_time_ms"] == snap["time"]
    assert set(offset_decoded) == {"plc_inputs", "plc_outputs"}
    assert offset_decoded["plc_inputs"]["X0"] is True
    print("  PASS — partial reads decode exactly the tags they cover, "
          "never words that were not read")
