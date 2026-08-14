"""
modbus_collector.py — Reference Collector for the Twin Shim

Polls the Modbus shim and emits a trace in THIS repo's existing real
trace format, so src/bridge/ compares collector output against twin
output with no changes to the bridge at all.

This is the reference implementation the platform repo's real_adapter
mirrors. It exists here, against the twin, so the trace contract is
proven before any of it is pointed at a real machine — the bench rig
gate from the platform brief, applied to the software rather than the
wiring.

WHAT MAKES THE TRACES COMPARABLE
--------------------------------
Two things, and both are decisions rather than details:

  1. THE TIMESTAMP COMES FROM THE DEVICE. Registers 0-1 carry the
     twin's own scan time, so the trace timestamp IS the scan
     timestamp and the trace declares TS_SCAN. Traces then align at
     tolerance 0. A collector that stamps on arrival instead declares
     TS_ARRIVAL, and align_traces will refuse tolerance 0 on it —
     correctly, because poll phase and network jitter are then baked
     into every timestamp.

  2. THE PROGRAM TRAVELS WITH THE TRACE. X1 is the position sensor
     under shuttle_control.st and the fault sensor under
     motor_start.st. A trace carrying X1=True without its program is
     ambiguous, so the collector records which program the shim is
     running and the trace carries it as provenance.

  3. THE REGISTER MAP IS VERIFIED BEFORE ANYTHING IS DECODED. The
     device publishes its map version in a register; the collector
     reads it on connect and REFUSES a mismatch. A stale map does not
     fail — it decodes into plausible wrong values, which is the same
     failure class as a wrong scale factor and just as invisible. The
     version is recorded in the trace's provenance too, so a trace
     says which map produced it.

SAFETY
------
Read-only by construction: the only Modbus function codes this module
can emit are FC3 and FC4, and the shim implements no write path to
call even if it tried.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "src/bridge")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from modbus_server import read_registers, FC_READ_INPUT_REGISTERS
from tag_map import make_twin_tag_map, PROTOCOL_VERSION
from trace_aligner import wrap_trace, TS_SCAN


class ProtocolVersionMismatch(IOError):
    """The device's register map is not the one this collector decodes."""


class ModbusCollector:
    """
    Polls a Modbus shim and builds real traces from it.

    Read-only. Holds one connection and reuses it, rather than
    reconnecting per poll — a device's connection budget is finite,
    and churning connections is how a collector knocks an HMI off its
    own PLC.

    CONTRACT CHECK ON CONNECT
    -------------------------
    The register layout is a published contract, and the device carries
    its version in a register. This collector reads that BEFORE it
    decodes anything, and REFUSES a mismatch rather than warning about
    it.

    That severity is the point. A stale register map does not fail
    loudly — it decodes successfully into plausible, wrong values:
    position off by a factor, a bit read from the wrong offset, a
    counter interpreted as a timestamp. That is the same failure class
    as a wrong scale factor, which silently corrupts every downstream
    KPI for the life of the system. A collector that continues past a
    version mismatch is choosing to produce data nobody can trust and
    nobody can spot.
    """

    def __init__(self, host, port, tag_map=None, unit_id=1,
                 program=None, timeout=5.0,
                 expected_protocol_version=PROTOCOL_VERSION,
                 verify_on_connect=True):
        """
        Args:
            expected_protocol_version : int — the register-map version
                this collector was written against
            verify_on_connect : bool — check it before the first decode.
                Disable only to inspect a device you already know is
                mismatched; never in acquisition.
        """
        self.host    = host
        self.port    = port
        self.unit_id = unit_id
        self.timeout = timeout
        self.tag_map = tag_map or make_twin_tag_map(program=program)
        self.program = program or self.tag_map.program

        self.expected_protocol_version = expected_protocol_version
        self.verify_on_connect         = verify_on_connect
        self.device_protocol_version   = None

        self._txn      = 0
        self._verified = False
        self.poll_count = 0
        self.missed_scans = 0
        self._last_scan_count = None

    def _version_address(self):
        """Where protocol_version lives, per the tag map — not hardcoded."""
        for tag in self.tag_map.tags:
            if tag.name == "protocol_version":
                return tag.address
        raise ProtocolVersionMismatch(
            "this tag map declares no protocol_version tag, so the "
            "device's register-map version cannot be checked")

    def verify_contract(self):
        """
        Read the device's protocol_version and refuse a mismatch.

        Called automatically before the first decode. Safe to call
        again; it re-reads and re-checks.

        Returns:
            int — the device's protocol version

        Raises:
            ProtocolVersionMismatch — if it differs from the version
            this collector decodes.
        """
        address = self._version_address()
        self._txn = (self._txn + 1) & 0xFFFF
        values, exception = read_registers(
            self.host, self.port, address, 1,
            function_code=FC_READ_INPUT_REGISTERS,
            unit_id=self.unit_id, transaction_id=self._txn,
            timeout=self.timeout)

        if exception is not None:
            raise ProtocolVersionMismatch(
                f"Modbus exception {exception} reading protocol_version "
                f"at register {address} from {self.host}:{self.port}")

        device_version = values[0]
        self.device_protocol_version = device_version

        if device_version != self.expected_protocol_version:
            raise ProtocolVersionMismatch(
                f"register-map version mismatch: {self.host}:{self.port} "
                f"reports protocol_version {device_version}, this "
                f"collector decodes version "
                f"{self.expected_protocol_version}. Refusing to poll — "
                f"decoding a stale map does not fail, it produces "
                f"plausible wrong values. Regenerate the collector's tag "
                f"map from the device's map "
                f"(`loom-shim map`, or GET /map) before acquiring.")

        self._verified = True
        return device_version

    def poll(self):
        """
        Read the full register image once and decode it.

        Verifies the register-map version on the first call.

        Returns:
            dict — decoded engineering values, plus "signals", the flat
            {symbol: bool} view the trace format wants.
        """
        if self.verify_on_connect and not self._verified:
            self.verify_contract()

        self._txn = (self._txn + 1) & 0xFFFF
        values, exception = read_registers(
            self.host, self.port, 0, self.tag_map.size,
            function_code=FC_READ_INPUT_REGISTERS,
            unit_id=self.unit_id, transaction_id=self._txn,
            timeout=self.timeout)

        if exception is not None:
            raise IOError(f"Modbus exception {exception} polling "
                          f"{self.host}:{self.port}")

        decoded = self.tag_map.decode(values)
        self.poll_count += 1

        # scan_count exists to detect missed polls. A collector that
        # cannot tell "nothing changed" from "I wasn't looking" reports
        # both as the same thing.
        scan_count = decoded.get("scan_count")
        if self._last_scan_count is not None and scan_count is not None:
            delta = (scan_count - self._last_scan_count) & 0xFFFF
            if delta > 1:
                self.missed_scans += delta - 1
        self._last_scan_count = scan_count

        decoded["signals"] = self._signals(decoded)
        return decoded

    @staticmethod
    def _signals(decoded):
        """Flatten the PLC input and output words to {symbol: bool}."""
        signals = {}
        signals.update(decoded.get("plc_inputs", {}))
        signals.update(decoded.get("plc_outputs", {}))
        return signals

    def trace_entry(self, decoded):
        """
        One real-trace entry, in the format real_trace.py validates.

        The timestamp is the DEVICE's scan time, not arrival time.
        """
        return {
            "time":    decoded["scan_time_ms"],
            "signals": dict(decoded["signals"]),
        }

    def record(self, samples, step_fn=None):
        """
        Record a trace of `samples` polls.

        Args:
            samples : int — how many polls to take
            step_fn : callable | None — invoked between polls. Passing
                      a runtime's step_scan here makes the recording
                      deterministic; passing None polls a free-running
                      shim against the wall clock.

        Returns:
            a WRAPPED trace declaring TS_SCAN provenance and the
            program, ready for align_traces / diff_traces.
        """
        entries = []
        for _ in range(samples):
            if step_fn is not None:
                step_fn()
            entries.append(self.trace_entry(self.poll()))

        return wrap_trace(entries, TS_SCAN,
                          program=self.program,
                          device=f"modbus://{self.host}:{self.port}",
                          collector="ModbusCollector",
                          protocol_version=self.device_protocol_version)


if __name__ == "__main__":
    import time as _time

    from twin_runtime import make_runtime
    from modbus_server import ModbusTwinServer
    from trace_diff import diff_traces
    from real_trace import validate_real_trace
    from trace_aligner import unwrap_trace

    print("=" * 60)
    print("Phase 11 - Step 8: Reference Modbus Collector")
    print("=" * 60)

    # A runtime we step by hand, so the recording is deterministic and
    # the comparison is exact rather than approximate.
    rt = make_runtime()
    server = ModbusTwinServer(rt, host="127.0.0.1", port=0)
    host, port = server.server_address
    server.start_thread()
    _time.sleep(0.2)

    collector = ModbusCollector(host, port, program=rt.program)
    print(f"\n  shim      : modbus://{host}:{port}")
    print(f"  program   : {collector.program}")
    print(f"  registers : {collector.tag_map.size}")

    # -------------------------------------------------------
    # Test 1: recorded trace validates as a real trace
    # -------------------------------------------------------
    print("\nTest 1 — Recorded trace is a valid real trace:")
    SAMPLES = 200
    real = collector.record(SAMPLES, step_fn=rt.step_scan)
    entries, prov = unwrap_trace(real)
    validation = validate_real_trace(entries)
    print(f"  {len(entries)} entries, valid={validation['valid']}, "
          f"errors={validation['errors']}")
    print(f"  provenance: {prov}")
    print(f"  first: {entries[0]}")
    print(f"  last : {entries[-1]}")

    # -------------------------------------------------------
    # Test 2: the sim side, from the same runtime
    # -------------------------------------------------------
    print("\nTest 2 — Diff against the twin's own trace, unchanged bridge:")
    # Re-run the identical scenario and take the runtime's own view.
    rt_ref = make_runtime()
    sim_entries = []
    for _ in range(SAMPLES):
        rt_ref.step_scan()
        sim_entries.append(rt_ref.trace_entry())
    sim = wrap_trace(sim_entries, TS_SCAN, program=rt_ref.program)

    diff = diff_traces(sim, real, tolerance_ms=0)
    print(f"  aligned         : {diff['alignment']['total_aligned']}"
          f"/{diff['alignment']['total_sim']} at tolerance 0")
    print(f"  compared        : {diff['total_compared']} signal checks")
    print(f"  mismatches      : {diff['total_mismatches']}")
    print(f"  program         : {diff['program']}")
    print(f"  trustworthy     : {diff['trustworthy']}")
    print(f"  offsets         : min={diff['alignment']['offsets']['min_ms']} "
          f"max={diff['alignment']['offsets']['max_ms']} "
          f"cascade={diff['alignment']['offsets']['cascade_suspected']}")
    print(f"  warnings        : {diff['warnings'] or 'none'}")

    # -------------------------------------------------------
    # Test 3: transitions mode over the same pair
    # -------------------------------------------------------
    print("\nTest 3 — Transitions mode:")
    tdiff = diff_traces(sim, real, tolerance_ms=0, mode="transitions")
    print(f"  compression : sim "
          f"{tdiff['compression']['sim']['total_entries']}→"
          f"{tdiff['compression']['sim']['kept_entries']}, real "
          f"{tdiff['compression']['real']['total_entries']}→"
          f"{tdiff['compression']['real']['kept_entries']}")
    print(f"  edge checks : {tdiff['total_compared']}")
    print(f"  mismatches  : {tdiff['total_mismatches']}")

    # -------------------------------------------------------
    # Test 4: a wrong-program trace is caught, not mislabelled
    # -------------------------------------------------------
    print("\nTest 4 — Program mismatch is caught:")
    mislabelled = wrap_trace(entries, TS_SCAN,
                             program="programs/motor_start.st")
    bad = diff_traces(sim, mislabelled, tolerance_ms=0)
    print(f"  sim declares  : {sim['provenance']['program']}")
    print(f"  real declares : programs/motor_start.st")
    for w in bad["warnings"]:
        print(f"  [warn] {w}")

    # -------------------------------------------------------
    # Test 5: missed-poll detection
    # -------------------------------------------------------
    print("\nTest 5 — Missed polls detected via scan_count:")
    before = collector.missed_scans
    for _ in range(5):
        rt.step_scan()          # runtime advances 5 scans...
    collector.poll()            # ...but the collector only polls once
    print(f"  advanced 5 scans between polls → "
          f"missed_scans {before} → {collector.missed_scans}")

    server.shutdown()
    server.server_close()

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert validation["valid"], f"trace invalid: {validation['errors']}"
    assert len(entries) == SAMPLES
    print(f"  PASS — {SAMPLES} entries validate against real_trace.py "
          f"unchanged")

    assert prov["timestamp"] == TS_SCAN, \
        "the collector must declare scan-timestamp provenance"
    assert prov["program"] == rt.program
    assert prov["device"].startswith("modbus://")
    print(f"  PASS — trace declares TS_SCAN, program and device")

    assert diff["alignment"]["total_aligned"] == SAMPLES, \
        "scan timestamps must align exactly at tolerance 0"
    assert diff["alignment"]["tolerance_ms"] == 0
    print(f"  PASS — {SAMPLES}/{SAMPLES} aligned at TOLERANCE 0 — the "
          f"device's scan time, not arrival time")

    assert diff["total_mismatches"] == 0, \
        f"collector and twin must agree: {diff['mismatches'][:3]}"
    assert diff["total_compared"] == SAMPLES * 5, \
        "5 signals (X0 X1 X2 Y0 Y1) per scan"
    print(f"  PASS — 0 mismatches across {diff['total_compared']} signal "
          f"checks; Modbus transport is lossless")

    assert diff["trustworthy"] is True
    assert diff["alignment"]["offsets"]["nonzero_offset_pairs"] == 0
    assert diff["warnings"] == [], f"unexpected: {diff['warnings']}"
    print("  PASS — no offsets, no cascade, no provenance warnings")

    assert tdiff["total_mismatches"] == 0, \
        f"transitions mode must agree too: {tdiff['mismatches'][:3]}"
    assert tdiff["compression"]["sim"]["kept_entries"] < SAMPLES, \
        "compression must actually compress"
    print(f"  PASS — transitions mode agrees "
          f"({tdiff['compression']['sim']['kept_entries']} transitions "
          f"from {SAMPLES} scans)")

    assert any("program mismatch" in w for w in bad["warnings"]), \
        "a trace from another program must be flagged"
    print("  PASS — program mismatch flagged rather than silently diffed")

    assert collector.missed_scans >= 4, \
        "skipping 5 scans must register as missed polls"
    print(f"  PASS — {collector.missed_scans} missed scans detected "
          f"(a collector must tell 'nothing changed' from 'not looking')")

    # -------------------------------------------------------
    # Test 6: the register-map contract is checked on connect
    # -------------------------------------------------------
    print("\nTest 6 — protocol_version checked on connect:")

    rt6 = make_runtime()
    server6 = ModbusTwinServer(rt6, host="127.0.0.1", port=0)
    h6, p6 = server6.server_address
    server6.start_thread()
    _time.sleep(0.2)

    ok_collector = ModbusCollector(h6, p6, program=rt6.program)
    ok_collector.poll()
    print(f"  matching version   → verified, "
          f"device reports {ok_collector.device_protocol_version}")

    stale = ModbusCollector(h6, p6, program=rt6.program,
                            expected_protocol_version=999)
    refused = None
    decoded_anyway = None
    try:
        decoded_anyway = stale.poll()
    except ProtocolVersionMismatch as exc:
        refused = str(exc)
    print(f"  stale collector    → refused")
    print(f"    {refused[:88]}...")
    print(f"  polls completed    → {stale.poll_count} "
          f"(refused BEFORE decoding, not after)")

    # A trace records the version it was collected under.
    traced = ok_collector.record(3, step_fn=rt6.step_scan)
    print(f"  trace provenance   → "
          f"protocol_version={traced['provenance']['protocol_version']}")

    server6.shutdown()
    server6.server_close()

    assert ok_collector.device_protocol_version == PROTOCOL_VERSION
    assert ok_collector._verified is True
    print(f"  PASS — matching version verified on connect")

    assert refused is not None, "a version mismatch must be refused"
    assert "Refusing to poll" in refused
    assert decoded_anyway is None, \
        "no data may be returned from a mismatched device"
    assert stale.poll_count == 0, \
        "the refusal must happen before any decode, not after"
    print("  PASS — mismatched register map refused before decoding; "
          "no plausible-wrong values produced")

    assert traced["provenance"]["protocol_version"] == PROTOCOL_VERSION, \
        "the trace must record which map version produced it"
    print("  PASS — trace provenance records the register-map version")
