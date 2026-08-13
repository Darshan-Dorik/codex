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


def make_twin_tag_map(program="programs/shuttle_control.st"):
    """
    The standard register map for a TwinRuntime.

    Addresses 0-1 are the load-bearing ones for trace comparison: they
    carry the twin's own SCAN TIME. A collector that records this as
    the trace timestamp produces traces that align against sim traces
    at tolerance 0, because the timestamp IS the scan timestamp. A
    collector that stamps on arrival instead needs a tolerance window
    for no reason — see trace_aligner.TS_SCAN vs TS_ARRIVAL.
    """
    tags = [
        Tag(0, "scan_time_ms", "uint32",
            lambda s: s["time"], unit="ms",
            note="TwinRuntime.t_ms — PLC scan timestamp. Record this as "
                 "the trace timestamp (TS_SCAN) so traces align exactly. "
                 "Wraps after ~49.7 days."),

        Tag(2, "shuttle_position", "uint16",
            lambda s: s["shuttle_position"], unit="deg", scale=0.01,
            note="CyclicShuttleModel.position, 0-360 deg, x100. "
                 "Max 35999 fits uint16."),

        Tag(3, "motor_state", "enum",
            lambda s: s["motor_state"],
            note="MotorStateMachine.state: "
                 "0=STOPPED 1=STARTING 2=RUNNING 3=STOPPING"),

        Tag(4, "cycles_completed", "uint16",
            lambda s: s["cycles_completed"], unit="count",
            note="CyclicShuttleModel.cycles_completed; wraps at 65535"),

        Tag(5, "jam_detected", "uint16",
            lambda s: 1 if s["jam_detected"] else 0,
            note="Jam injector state; mirrors PLC input X2"),

        Tag(6, "scan_count", "uint16",
            lambda s: s["scan_count"] & 0xFFFF, unit="count",
            note="PLC scans since start; wraps at 65535. Exists so a "
                 "collector can detect MISSED POLLS, not to measure time"),

        Tag(7, "protocol_version", "uint16",
            lambda s: PROTOCOL_VERSION,
            note="Shim register-map version; bump on any layout change"),

        Tag(8, "plc_inputs", "bitfield",
            lambda s: s["sensors"],
            bits={0: "X0", 1: "X1", 2: "X2"},
            note="PLC input image. Bit meanings are PROGRAM-SCOPED: "
                 "under shuttle_control.st X0=run command, "
                 "X1=position sensor, X2=jam sensor"),

        Tag(9, "plc_outputs", "bitfield",
            lambda s: s["outputs"],
            bits={0: "Y0", 1: "Y1"},
            note="PLC output image. Under shuttle_control.st "
                 "Y0=shuttle motor, Y1=position indicator. These exist "
                 "only because the PLC is in the loop"),
    ]
    return TagMap(tags, program=program)


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

    assert abs(decoded["shuttle_position"] - snap["shuttle_position"]) < 0.01
    print(f"  PASS — shuttle_position round-trips within scale "
          f"({decoded['shuttle_position']} deg)")

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
