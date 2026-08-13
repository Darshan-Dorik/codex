"""
modbus_server.py — Read-Only Modbus TCP Server over the Twin

Serves TwinRuntime state as Modbus TCP registers so the twin can be
polled exactly like a real machine. This is the Phase 1 bench
simulator: the thing a collector is developed and soak-tested against
before it is ever pointed at a production line.

Stdlib only — MBAP framing and the PDU codec are implemented here.

READ-ONLY, STRUCTURALLY
-----------------------
Only FC3 (Read Holding Registers) and FC4 (Read Input Registers) are
implemented. There is no write path to disable, audit or trust: the
dispatch table contains no write function code, and WRITE_FUNCTION_CODES
is asserted disjoint from it at import time and again in the tests.
Every write request is answered with exception 0x01 (Illegal Function)
by the same default branch that handles any unknown code.

This is the difference between "we reviewed the code and found no
writes" and "no write exists to find" — the platform brief's
passive-only assertion, done as a property rather than a claim.

FC3 IS AN ALIAS OF FC4
----------------------
Real drives expose process data as holding registers — the Delta MS300
profile in the platform brief reads 0x2103 that way — so a collector
written against real hardware polls FC3. Serving the same read-only
image on both means the bench target does not quietly train the
collector to use a function code the field will not answer.

WHY THE SCAN TIME IS IN THE REGISTERS
-------------------------------------
Registers 0-1 carry the twin's own scan timestamp. A collector that
records THAT as its trace timestamp produces traces that align against
sim traces at tolerance 0. A collector that stamps on arrival instead
needs a tolerance window forever, for no reason other than that it
threw the exact timestamp away.

FAULT INJECTION
---------------
The standing test requirements call for a fault injector. Delay, drop,
garbage and half-open are all COUNTER-based, never random, so a failing
soak run reproduces exactly.
"""

import os
import socket
import socketserver
import struct
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tag_map import make_twin_tag_map

# --- Function codes -------------------------------------------------

FC_READ_HOLDING_REGISTERS = 0x03
FC_READ_INPUT_REGISTERS   = 0x04

# Every write function code in the Modbus spec. Named so the read-only
# property can be asserted rather than described.
WRITE_FUNCTION_CODES = frozenset({
    0x05,  # Write Single Coil
    0x06,  # Write Single Register
    0x0F,  # Write Multiple Coils
    0x10,  # Write Multiple Registers
    0x16,  # Mask Write Register
    0x17,  # Read/Write Multiple Registers  (contains a write)
    0x15,  # Write File Record
    0x08,  # Diagnostics (can reset counters / force listen-only)
})

READ_FUNCTION_CODES = frozenset({
    FC_READ_HOLDING_REGISTERS,
    FC_READ_INPUT_REGISTERS,
})

# --- Exception codes ------------------------------------------------

EX_ILLEGAL_FUNCTION     = 0x01
EX_ILLEGAL_DATA_ADDRESS = 0x02
EX_ILLEGAL_DATA_VALUE   = 0x03

# Modbus caps a register read at 125 words per transaction.
MAX_REGISTERS_PER_READ = 125

MBAP_HEADER_LEN = 7
PROTOCOL_ID     = 0


# ---------------------------------------------------------------------------
# PDU codec — pure functions, no sockets, so they can be tested on bytes
# ---------------------------------------------------------------------------

def exception_pdu(function_code, exception_code):
    """Build an exception response PDU."""
    return struct.pack(">BB", (function_code | 0x80) & 0xFF, exception_code)


def handle_pdu(pdu, registers):
    """
    Handle one request PDU against a register image.

    This is the whole protocol surface. It touches no socket and no
    runtime state, so the tests drive it with literal bytes.

    Args:
        pdu       : bytes — request PDU (function code + data)
        registers : list[int] — the register image

    Returns:
        bytes — response PDU (normal or exception)
    """
    if len(pdu) < 1:
        return exception_pdu(0, EX_ILLEGAL_FUNCTION)

    function_code = pdu[0]

    # The only branch that reads. Anything else — including every
    # write function code — falls through to Illegal Function.
    if function_code not in READ_FUNCTION_CODES:
        return exception_pdu(function_code, EX_ILLEGAL_FUNCTION)

    if len(pdu) != 5:
        return exception_pdu(function_code, EX_ILLEGAL_DATA_VALUE)

    _, start, quantity = struct.unpack(">BHH", pdu)

    if quantity < 1 or quantity > MAX_REGISTERS_PER_READ:
        return exception_pdu(function_code, EX_ILLEGAL_DATA_VALUE)

    if start + quantity > len(registers):
        return exception_pdu(function_code, EX_ILLEGAL_DATA_ADDRESS)

    words = registers[start:start + quantity]
    body  = b"".join(struct.pack(">H", w & 0xFFFF) for w in words)
    return struct.pack(">BB", function_code, len(body)) + body


def decode_mbap(header):
    """Decode a 7-byte MBAP header into (txn, proto, length, unit)."""
    return struct.unpack(">HHHB", header)


def encode_response(transaction_id, unit_id, pdu):
    """Wrap a response PDU in its MBAP header."""
    return struct.pack(">HHHB", transaction_id, PROTOCOL_ID,
                       len(pdu) + 1, unit_id) + pdu


def build_request(transaction_id, unit_id, function_code, start, quantity):
    """Build a full request frame. Used by the tests and the client."""
    pdu = struct.pack(">BHH", function_code, start, quantity)
    return struct.pack(">HHHB", transaction_id, PROTOCOL_ID,
                       len(pdu) + 1, unit_id) + pdu


# ---------------------------------------------------------------------------
# Deterministic fault injection
# ---------------------------------------------------------------------------

class FaultInjector:
    """
    Counter-based fault injection for bench testing.

    Deterministic by construction — the repo forbids unseeded
    randomness, and a soak failure that cannot be reproduced is not a
    finding, it is a rumour.
    """

    def __init__(self, delay_ms=0, drop_every_n=0, garbage_every_n=0,
                 half_open_every_n=0):
        self.delay_ms          = delay_ms
        self.drop_every_n      = drop_every_n
        self.garbage_every_n   = garbage_every_n
        self.half_open_every_n = half_open_every_n
        self._count            = 0
        self._lock             = threading.Lock()

    def next_action(self):
        """
        Advance the counter and return what to do with this request.

        Returns:
            (action, delay_ms) where action is
            "respond" | "drop" | "garbage" | "half_open"
        """
        with self._lock:
            self._count += 1
            n = self._count

        def due(every):
            return every > 0 and n % every == 0

        if due(self.half_open_every_n):
            return "half_open", self.delay_ms
        if due(self.garbage_every_n):
            return "garbage", self.delay_ms
        if due(self.drop_every_n):
            return "drop", self.delay_ms
        return "respond", self.delay_ms

    @property
    def active(self):
        return any((self.delay_ms, self.drop_every_n,
                    self.garbage_every_n, self.half_open_every_n))


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def _recv_exact(sock, count):
    """Read exactly count bytes, or return None if the peer closed."""
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class _Handler(socketserver.BaseRequestHandler):

    def handle(self):
        server = self.server
        if not server._acquire_connection():
            # Connection budget exhausted. A real S7-1200 or Modbus
            # gateway has finite connection resources, and exhausting
            # them drops the machine's own HMI. Refusing here lets the
            # collector's connection discipline be tested on the bench
            # instead of discovered on a production line.
            server.rejected_connections += 1
            self.request.close()
            return

        try:
            self.request.settimeout(server.socket_timeout)
            while True:
                header = _recv_exact(self.request, MBAP_HEADER_LEN)
                if header is None:
                    return

                txn, proto, length, unit = decode_mbap(header)

                if proto != PROTOCOL_ID:
                    return                      # not Modbus TCP; drop it
                if length < 2 or length > 260:
                    return                      # implausible frame

                pdu = _recv_exact(self.request, length - 1)
                if pdu is None:
                    return

                server.requests_served += 1

                action, delay_ms = server.faults.next_action()
                if delay_ms:
                    import time as _t
                    _t.sleep(delay_ms / 1000.0)

                if action == "drop":
                    server.faults_injected["drop"] += 1
                    continue                    # silence; client times out
                if action == "half_open":
                    server.faults_injected["half_open"] += 1
                    self.request.close()
                    return
                if action == "garbage":
                    server.faults_injected["garbage"] += 1
                    self.request.sendall(b"\xde\xad\xbe\xef")
                    continue

                registers = server.registers()
                response  = encode_response(txn, unit,
                                            handle_pdu(pdu, registers))
                self.request.sendall(response)
        except (socket.timeout, ConnectionResetError, BrokenPipeError):
            return
        finally:
            server._release_connection()

    def finish(self):
        try:
            super().finish()
        except (BrokenPipeError, ConnectionResetError):
            pass


class ModbusTwinServer(socketserver.ThreadingTCPServer):
    """
    Read-only Modbus TCP server over a TwinRuntime.

    The runtime is polled through snapshot(), so the server never
    touches simulation state and cannot perturb it.
    """

    allow_reuse_address = True
    daemon_threads      = True

    def __init__(self, runtime, tag_map=None, host="127.0.0.1", port=5502,
                 max_connections=4, faults=None, socket_timeout=30.0):
        self.runtime         = runtime
        self.tag_map         = tag_map or make_twin_tag_map(
            program=getattr(runtime, "program", None))
        self.max_connections = max_connections
        self.faults          = faults or FaultInjector()
        self.socket_timeout  = socket_timeout

        self.active_connections   = 0
        self.rejected_connections = 0
        self.requests_served      = 0
        self.faults_injected      = {"drop": 0, "garbage": 0,
                                     "half_open": 0}
        self._conn_lock = threading.Lock()

        super().__init__((host, port), _Handler)

    def registers(self):
        """Current register image, rendered from one snapshot."""
        return self.tag_map.render(self.runtime.snapshot())

    def _acquire_connection(self):
        with self._conn_lock:
            if self.active_connections >= self.max_connections:
                return False
            self.active_connections += 1
            return True

    def _release_connection(self):
        with self._conn_lock:
            self.active_connections = max(0, self.active_connections - 1)

    def start_thread(self):
        t = threading.Thread(target=self.serve_forever, daemon=True)
        t.start()
        return t


# Read-only is a property of this module, checked at import.
assert not (READ_FUNCTION_CODES & WRITE_FUNCTION_CODES), \
    "a write function code has been added to the read set"


# ---------------------------------------------------------------------------
# Minimal stdlib client — for tests and for poking the shim by hand
# ---------------------------------------------------------------------------

def read_registers(host, port, start, quantity,
                   function_code=FC_READ_INPUT_REGISTERS,
                   unit_id=1, transaction_id=1, timeout=5.0, sock=None):
    """
    Read registers from a Modbus TCP server.

    Returns:
        (values, exception_code) — exception_code is None on success,
        and values is None when the server returned an exception.
    """
    own_socket = sock is None
    if own_socket:
        sock = socket.create_connection((host, port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall(build_request(transaction_id, unit_id, function_code,
                                   start, quantity))
        header = _recv_exact(sock, MBAP_HEADER_LEN)
        if header is None:
            raise ConnectionError("server closed before responding")
        txn, proto, length, unit = decode_mbap(header)
        pdu = _recv_exact(sock, length - 1)
        if pdu is None:
            raise ConnectionError("server closed mid-PDU")

        if pdu[0] & 0x80:
            return None, pdu[1]

        byte_count = pdu[1]
        values = list(struct.unpack(">" + "H" * (byte_count // 2),
                                    pdu[2:2 + byte_count]))
        return values, None
    finally:
        if own_socket:
            sock.close()


if __name__ == "__main__":
    import time as _time

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from twin_runtime import make_runtime

    print("=" * 60)
    print("Phase 11 - Step 7: Read-Only Modbus TCP Shim")
    print("=" * 60)

    tm = make_twin_tag_map()
    rt = make_runtime()
    rt.run_until(2000)
    image = tm.render(rt.snapshot())

    # -------------------------------------------------------
    # Test 1: PDU codec on literal bytes, no sockets
    # -------------------------------------------------------
    print("\nTest 1 — PDU codec (literal bytes):")

    req_pdu = struct.pack(">BHH", FC_READ_INPUT_REGISTERS, 0, 2)
    rsp_pdu = handle_pdu(req_pdu, image)
    print(f"  FC4 read 0..1  req={req_pdu.hex()}  rsp={rsp_pdu.hex()}")
    scan_time = (struct.unpack(">H", rsp_pdu[2:4])[0] << 16) | \
        struct.unpack(">H", rsp_pdu[4:6])[0]
    print(f"    decoded scan_time_ms = {scan_time}")

    rsp_fc3 = handle_pdu(struct.pack(">BHH", FC_READ_HOLDING_REGISTERS, 0, 2),
                         image)
    print(f"  FC3 same read  rsp={rsp_fc3.hex()}  "
          f"(alias, differs only in the echoed function code)")

    # -------------------------------------------------------
    # Test 2: THE READ-ONLY PROOF
    # -------------------------------------------------------
    print("\nTest 2 — Read-only proof:")
    print(f"  implemented function codes : "
          f"{sorted(hex(c) for c in READ_FUNCTION_CODES)}")
    print(f"  write function codes       : "
          f"{sorted(hex(c) for c in WRITE_FUNCTION_CODES)}")
    print(f"  intersection               : "
          f"{READ_FUNCTION_CODES & WRITE_FUNCTION_CODES or '{} (empty)'}")

    write_results = {}
    for fc in sorted(WRITE_FUNCTION_CODES):
        # A well-formed write request, answered anyway.
        pdu = struct.pack(">BHH", fc, 0, 1)
        rsp = handle_pdu(pdu, image)
        write_results[fc] = (rsp[0], rsp[1])
        print(f"    FC 0x{fc:02X} → rsp {rsp.hex()} "
              f"(fc|0x80={rsp[0]:#04x}, exception={rsp[1]})")

    # -------------------------------------------------------
    # Test 3: exceptions
    # -------------------------------------------------------
    print("\nTest 3 — Exception cases:")
    cases = {
        "quantity 0":
            struct.pack(">BHH", FC_READ_INPUT_REGISTERS, 0, 0),
        "quantity 126 (> 125)":
            struct.pack(">BHH", FC_READ_INPUT_REGISTERS, 0, 126),
        "address past end":
            struct.pack(">BHH", FC_READ_INPUT_REGISTERS, len(image), 1),
        "read spanning the end":
            struct.pack(">BHH", FC_READ_INPUT_REGISTERS, len(image) - 1, 4),
        "unknown function 0x2B":
            struct.pack(">BHH", 0x2B, 0, 1),
        "truncated PDU":
            struct.pack(">BH", FC_READ_INPUT_REGISTERS, 0),
    }
    exceptions = {}
    for label, pdu in cases.items():
        rsp = handle_pdu(pdu, image)
        exceptions[label] = rsp[1]
        print(f"  {label:24} → exception {rsp[1]}")

    # -------------------------------------------------------
    # Test 4: live server over a real socket
    # -------------------------------------------------------
    print("\nTest 4 — Live server on a real socket:")
    rt_live = make_runtime()
    rt_live.start_thread()
    server = ModbusTwinServer(rt_live, host="127.0.0.1", port=0)
    host, port = server.server_address
    server.start_thread()
    _time.sleep(0.2)
    print(f"  listening on {host}:{port}")

    vals_fc4, exc4 = read_registers(host, port, 0, 10,
                                    FC_READ_INPUT_REGISTERS)
    vals_fc3, exc3 = read_registers(host, port, 0, 10,
                                    FC_READ_HOLDING_REGISTERS)
    print(f"  FC4 read 0..9 → {vals_fc4}")
    print(f"  FC3 read 0..9 → {vals_fc3}")

    decoded_live = tm.decode(vals_fc4)
    print(f"  decoded: t={decoded_live['scan_time_ms']}ms "
          f"pos={decoded_live['shuttle_position']} "
          f"state={decoded_live['motor_state']} "
          f"in={decoded_live['plc_inputs']} out={decoded_live['plc_outputs']}")

    # Writes over the wire, not just through the codec.
    _, exc_write = read_registers(host, port, 0, 1, function_code=0x06)
    print(f"  FC 0x06 (Write Single Register) over the wire → "
          f"exception {exc_write}")

    # Time advances between polls — the shim is live, not a fixture.
    t1 = tm.decode(read_registers(host, port, 0, 2)[0])["scan_time_ms"]
    _time.sleep(0.25)
    t2 = tm.decode(read_registers(host, port, 0, 2)[0])["scan_time_ms"]
    print(f"  scan_time_ms advanced {t1}ms → {t2}ms across a 250ms gap")

    # -------------------------------------------------------
    # Test 5: connection budget
    # -------------------------------------------------------
    print("\nTest 5 — Connection budget (max 4):")
    held = []
    for i in range(4):
        s = socket.create_connection((host, port), timeout=5)
        vals, _ = read_registers(host, port, 0, 1, sock=s)
        held.append(s)
    print(f"  {len(held)} connections held, all answering")

    refused = False
    try:
        extra = socket.create_connection((host, port), timeout=5)
        extra.settimeout(5)
        extra.sendall(build_request(9, 1, FC_READ_INPUT_REGISTERS, 0, 1))
        if _recv_exact(extra, MBAP_HEADER_LEN) is None:
            refused = True
        extra.close()
    except (ConnectionError, socket.timeout):
        refused = True
    print(f"  5th connection → {'refused' if refused else 'ACCEPTED'} "
          f"(rejected_connections={server.rejected_connections})")

    for s in held:
        s.close()
    _time.sleep(0.3)

    # -------------------------------------------------------
    # Test 6: deterministic fault injection
    # -------------------------------------------------------
    print("\nTest 6 — Deterministic fault injection:")
    inj = FaultInjector(drop_every_n=3, garbage_every_n=5)
    actions = [inj.next_action()[0] for _ in range(15)]
    print(f"  drop_every_n=3, garbage_every_n=5 over 15 requests:")
    print(f"    {actions}")

    inj2 = FaultInjector(drop_every_n=3, garbage_every_n=5)
    actions2 = [inj2.next_action()[0] for _ in range(15)]
    print(f"  replayed → {'identical' if actions == actions2 else 'DIFFERENT'}")

    server.shutdown()
    server.server_close()

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert scan_time == rt.snapshot()["time"], \
        "scan time must survive the wire exactly"
    assert rsp_fc3[2:] == rsp_pdu[2:], \
        "FC3 must serve the same image as FC4"
    assert rsp_fc3[0] == FC_READ_HOLDING_REGISTERS
    print("  PASS — Test 1: FC4 decodes correctly; FC3 is a true alias")

    assert not (READ_FUNCTION_CODES & WRITE_FUNCTION_CODES), \
        "no write function code may be implemented"
    for fc, (echoed, exc) in write_results.items():
        assert echoed == (fc | 0x80), f"FC 0x{fc:02X} must echo fc|0x80"
        assert exc == EX_ILLEGAL_FUNCTION, \
            f"FC 0x{fc:02X} must return Illegal Function, got {exc}"
    print(f"  PASS — Test 2: all {len(write_results)} write function codes "
          f"return exception 0x01; the read set is provably disjoint from "
          f"the write set")

    assert exceptions["quantity 0"] == EX_ILLEGAL_DATA_VALUE
    assert exceptions["quantity 126 (> 125)"] == EX_ILLEGAL_DATA_VALUE
    assert exceptions["address past end"] == EX_ILLEGAL_DATA_ADDRESS
    assert exceptions["read spanning the end"] == EX_ILLEGAL_DATA_ADDRESS
    assert exceptions["unknown function 0x2B"] == EX_ILLEGAL_FUNCTION
    assert exceptions["truncated PDU"] == EX_ILLEGAL_DATA_VALUE
    print("  PASS — Test 3: illegal value / address / function all correct")

    assert vals_fc4 == vals_fc3, "FC3 and FC4 must agree over the wire"
    assert exc4 is None and exc3 is None
    assert decoded_live["plc_inputs"]["X0"] is True
    assert "Y0" in decoded_live["plc_outputs"]
    print("  PASS — Test 4: live reads over FC3 and FC4 agree and decode")

    assert exc_write == EX_ILLEGAL_FUNCTION, \
        "a write over the wire must be refused, not only in the codec"
    print("  PASS — Test 4: FC 0x06 refused over a real socket")

    assert t2 > t1, "the shim must be live, not a fixture"
    print(f"  PASS — Test 4: sim time advanced {t2 - t1}ms across the gap")

    assert server.rejected_connections >= 1, \
        "the connection budget must actually refuse"
    print(f"  PASS — Test 5: connection budget enforced "
          f"({server.rejected_connections} refused past {server.max_connections})")

    assert actions == actions2, "fault injection must be reproducible"
    assert actions[2] == "drop" and actions[5] == "drop"
    assert actions[4] == "garbage" and actions[9] == "garbage"
    assert actions[14] == "garbage", "15 is divisible by both; garbage wins"
    print(f"  PASS — Test 6: injection deterministic and replayable "
          f"({actions.count('drop')} drops, "
          f"{actions.count('garbage')} garbage)")
