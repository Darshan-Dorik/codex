"""
tool/loom_shim.py — Bench Simulator CLI

Runs the loom twin as a pollable machine, and produces the OPC UA model
that describes it.

Usage:
    python3 tool/loom_shim.py serve                    # Modbus + HTTP
    python3 tool/loom_shim.py serve --modbus-port 5502 --http-port 5174
    python3 tool/loom_shim.py serve --fault-drop-every 10
    python3 tool/loom_shim.py export                   # write NodeSet2
    python3 tool/loom_shim.py validate                 # XSD + structure
    python3 tool/loom_shim.py map                      # print register map

Commands:
    serve      Run the twin and serve it over Modbus TCP and HTTP
    export     Generate the OPC UA NodeSet2 file (build-time, no twin)
    validate   Validate the NodeSet against the XSD (build-time, no twin)
    map        Print the register map and protocol version

ONE RUNTIME, GENUINELY SHARED
-----------------------------
`serve` constructs exactly ONE TwinRuntime and hands the same object to
every face. The Modbus server and the HTTP `/state` endpoint both call
`runtime.snapshot()`, so a collector cross-checking register 4 against
the dashboard is comparing two views of ONE scan.

Two runtimes would be worse than useless here: they would drift apart
within seconds, and a collector cross-checking two faces would report
an inconsistency that does not exist on any real machine. If a face is
ever added that CANNOT share the runtime, that has to be stated at the
top of this file in the same breath as adding it.

OPC UA IS NOT SERVED LIVE FROM THIS REPO
----------------------------------------
`export` writes an information MODEL, not a running server. Nothing in
this repo answers OPC UA on a socket, so there is currently no way for
the OPC UA face to disagree with the Modbus face — the model is
build-time and carries no values.

When the platform repo serves this NodeSet with a real stack, the same
rule applies to it: the OPC UA server must read the same snapshot
source as the Modbus collector, or the two faces will disagree about
which scan they are describing.

BUILD-TIME COMMANDS RUN WITHOUT A TWIN
--------------------------------------
`export`, `validate` and `map` construct no TwinRuntime, open no
socket, and start no thread. They work in CI, which is where signal
drift between the two faces actually gets caught.
"""

import argparse
import os
import sys

# Ensure project root, tool/ and the shim package are importable.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOL = os.path.dirname(os.path.abspath(__file__))
for _subdir in ("", "src/core", "src/bridge", "src/shim"):
    _p = os.path.join(_ROOT, _subdir) if _subdir else _ROOT
    if _p not in sys.path:
        sys.path.insert(0, _p)
if _TOOL not in sys.path:
    sys.path.insert(0, _TOOL)

# Build-time imports only — nothing here starts a simulation.
from tag_map import (make_twin_signals, modbus_tag_map, PROTOCOL_VERSION)
from nodeset_export import (nodeset_xml, write_nodeset, structural_check,
                            DATATYPE_IDS)

DEFAULT_NODESET = os.path.join(_ROOT, "outputs", "nodesets",
                               "LoomTwin.NodeSet2.xml")
DEFAULT_XSD     = os.path.join(_ROOT, "src", "shim", "UANodeSet.xsd")
DEFAULT_PROGRAM = "programs/shuttle_control.st"


# ---------------------------------------------------------------------------
# map — print the register map (no twin)
# ---------------------------------------------------------------------------

def cmd_map(args):
    signals = make_twin_signals(program=args.program)
    tags    = modbus_tag_map(signals)

    print(f"Register map — protocol_version {PROTOCOL_VERSION}")
    print(f"  program   : {signals.program}")
    print(f"  namespace : {signals.namespace_uri}")
    print(f"  registers : {tags.size} words (FC3 and FC4, read-only)")
    print()
    print(f"  {'addr':>5}  {'tag':18} {'kind':9} {'unit':6} {'scale':>6}")
    print("  " + "-" * 54)
    for tag in tags.tags:
        span = (f"{tag.address}-{tag.address + tag.word_count - 1}"
                if tag.word_count > 1 else str(tag.address))
        print(f"  {span:>5}  {tag.name:18} {tag.kind:9} "
              f"{tag.unit:6} {tag.scale:>6}")
        for bit, symbol in sorted(tag.bits.items()):
            signal = next((s for s in signals.signals
                           if s.symbol == symbol), None)
            measure = f" — {signal.measure}" if signal else ""
            print(f"           bit {bit} = {symbol}{measure}")

    print()
    print(f"  {'topic':52} {'datatype':9} symbol")
    print("  " + "-" * 74)
    for signal in signals.signals:
        print(f"  {signals.topic(signal):52} {signal.datatype:9} "
              f"{signal.symbol or ''}")
    return 0


# ---------------------------------------------------------------------------
# export — write the NodeSet2 (no twin)
# ---------------------------------------------------------------------------

def cmd_export(args):
    signals = make_twin_signals(program=args.program)
    path    = write_nodeset(signals, args.out)
    size    = os.path.getsize(path)

    print(f"NodeSet2 written")
    print(f"  path      : {path} ({size} bytes)")
    print(f"  namespace : {signals.namespace_uri}")
    print(f"  program   : {signals.program}")
    print(f"  signals   : {len(signals.signals)} "
          f"across {len(signals.units())} units "
          f"({', '.join(signals.units())})")
    print(f"  version   : protocol_version {PROTOCOL_VERSION}")
    return 0


# ---------------------------------------------------------------------------
# validate — XSD + structural + face parity (no twin)
# ---------------------------------------------------------------------------

def check_faces_cover_same_signals(program=DEFAULT_PROGRAM):
    """
    Assert the Modbus and OPC UA faces project the SAME signals.

    Exposed as a function so tool/final_validation.py can run it too —
    drift between the two faces is exactly the kind of thing that gets
    committed when the check lives only in one module's own tests.

    Returns:
        {"ok": bool, "errors": [...], "signals": int, "registers": int}
    """
    import xml.etree.ElementTree as ET

    signals = make_twin_signals(program=program)
    tags    = modbus_tag_map(signals)

    # Datatypes are checked BEFORE building the NodeSet. An unaliased
    # datatype makes build_nodeset raise, and a check that dies on the
    # very drift it exists to report is not a check.
    bad_types = {s.measure: s.datatype for s in signals.signals
                 if s.datatype not in DATATYPE_IDS}
    if bad_types:
        return {
            "ok":     False,
            "errors": [f"datatypes with no OPC UA alias: {bad_types}"],
            "signals":   len({s.measure for s in signals.signals}),
            "registers": tags.size,
            "units":     signals.units(),
        }

    xml_text = nodeset_xml(signals)
    root = ET.fromstring(xml_text)
    ua_measures = {v.get("BrowseName").split(":", 1)[1]
                   for v in root if v.tag.endswith("UAVariable")}
    declared    = {s.measure for s in signals.signals}
    modbus_placed = {s.measure for s in signals.signals
                     if s.modbus is not None}

    errors = []
    if ua_measures != declared:
        errors.append(
            f"OPC UA face differs from the signal set: "
            f"missing={sorted(declared - ua_measures)} "
            f"extra={sorted(ua_measures - declared)}")
    if modbus_placed != declared:
        errors.append(
            f"Modbus face differs from the signal set: "
            f"unplaced={sorted(declared - modbus_placed)}")
    for signal in signals.signals:
        if signal.datatype not in DATATYPE_IDS:
            errors.append(f"{signal.measure}: datatype "
                          f"{signal.datatype!r} has no OPC UA alias")

    return {
        "ok":        not errors,
        "errors":    errors,
        "signals":   len(declared),
        "registers": tags.size,
        "units":     signals.units(),
    }


def cmd_validate(args):
    import shutil
    import subprocess

    signals  = make_twin_signals(program=args.program)
    xml_text = nodeset_xml(signals)
    failures = []

    print("Validating the OPC UA model (build-time; no twin required)")
    print()

    # --- 1. the two faces agree ---
    parity = check_faces_cover_same_signals(program=args.program)
    print(f"  faces      : {parity['signals']} signals → "
          f"{parity['registers']} registers / {parity['signals']} "
          f"UA variables")
    if parity["ok"]:
        print("               OK — Modbus and OPC UA project the same set")
    else:
        for err in parity["errors"]:
            print(f"               FAIL — {err}")
        failures.append("face parity")

    # --- 2. structure ---
    structural = structural_check(xml_text, signals)
    print(f"  structure  : {structural['counts']['objects']} objects, "
          f"{structural['counts']['variables']} variables")
    if structural["ok"]:
        print("               OK — read-only, no orphans, no duplicate ids")
    else:
        for err in structural["errors"]:
            print(f"               FAIL — {err}")
        failures.append("structure")

    # --- 3. XSD ---
    if not os.path.exists(args.out):
        write_nodeset(signals, args.out)
    xmllint = shutil.which("xmllint")
    if not os.path.exists(args.xsd):
        print(f"  xsd        : SKIP — schema not found at {args.xsd}")
    elif xmllint is None:
        print("  xsd        : SKIP — xmllint not installed")
    else:
        proc = subprocess.run(
            [xmllint, "--noout", "--schema", args.xsd, args.out],
            capture_output=True, text=True)
        if proc.returncode == 0:
            print(f"  xsd        : OK — validates against "
                  f"{os.path.basename(args.xsd)}")
        else:
            print(f"  xsd        : FAIL — exit {proc.returncode}")
            for line in (proc.stderr or "").strip().splitlines():
                print(f"               {line}")
            failures.append("xsd")

    # --- 4. real client (optional) ---
    try:
        import nodeset_client_check
        if nodeset_client_check.available():
            result = nodeset_client_check.check(args.out)
            if result["errors"] or result["writable"]:
                print(f"  client     : FAIL — {result['errors']} "
                      f"writable={result['writable']}")
                failures.append("client")
            else:
                print(f"  client     : OK — asyncua imported "
                      f"{result['imported_nodes']} nodes, "
                      f"{len(result['variables'])} variables browsable, "
                      f"all read-only")
        else:
            print("  client     : SKIP — asyncua not installed "
                  "(see src/shim/nodeset_client_check.py)")
    except Exception as exc:                       # noqa: BLE001
        print(f"  client     : SKIP — {type(exc).__name__}: {exc}")

    print()
    if failures:
        print(f"  ✗  VALIDATION FAILED: {', '.join(failures)}")
        return 1
    print("  ✓  MODEL VALID")
    return 0


# ---------------------------------------------------------------------------
# serve — one runtime, both live faces
# ---------------------------------------------------------------------------

def cmd_serve(args):
    import json
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    from twin_runtime import make_runtime
    from modbus_server import ModbusTwinServer, FaultInjector

    # THE ONE RUNTIME. Every face below is handed this exact object.
    runtime = make_runtime(program=args.program,
                           sim_step_ms=args.sim_step_ms,
                           scan_period_ms=args.scan_period_ms)
    signals = make_twin_signals(program=args.program)
    tags    = modbus_tag_map(signals)

    faults = FaultInjector(
        delay_ms=args.fault_delay_ms,
        drop_every_n=args.fault_drop_every,
        garbage_every_n=args.fault_garbage_every,
        half_open_every_n=args.fault_half_open_every)

    modbus = ModbusTwinServer(runtime, tag_map=tags,
                              host=args.host, port=args.modbus_port,
                              max_connections=args.max_connections,
                              faults=faults)

    class StateHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/state":
                body = json.dumps(runtime.snapshot()).encode()
            elif self.path == "/map":
                body = json.dumps(tags.describe()).encode()
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *a):
            pass

    http = HTTPServer((args.host, args.http_port), StateHandler)

    runtime.start_thread()
    modbus.start_thread()
    threading.Thread(target=http.serve_forever, daemon=True).start()

    modbus_host, modbus_port = modbus.server_address

    # Startup banner. Whoever points a collector at this from the
    # platform repo has no other way to know their register map matches.
    print("loom-shim — bench simulator")
    print()
    print("  ENDPOINTS")
    print(f"    Modbus TCP   modbus://{modbus_host}:{modbus_port} "
          f"(FC3/FC4, read-only)")
    print(f"    HTTP state   http://{args.host}:{args.http_port}/state")
    print(f"    HTTP map     http://{args.host}:{args.http_port}/map")
    print()
    print("  CONTRACT")
    print(f"    protocol_version  {PROTOCOL_VERSION}   "
          f"<- check this matches your collector")
    print(f"    registers         {tags.size} words, "
          f"scan time at 0-1 (uint32, ms)")
    print(f"    program           {signals.program}")
    print(f"    namespace         {signals.namespace_uri}")
    print(f"    signals           {len(signals.signals)} across "
          f"{len(signals.units())} units: {', '.join(signals.units())}")
    print()
    print("  RUNTIME")
    print(f"    scan period       {runtime.scan_period_ms}ms")
    print(f"    physics step      {runtime.sim_step_ms}ms "
          f"({runtime.rate_ratio}:1)")
    print(f"    max connections   {args.max_connections}")
    print(f"    ONE runtime shared by both faces — Modbus and HTTP read "
          f"the same scan")
    if faults.active:
        print()
        print("  FAULT INJECTION ACTIVE (deterministic, counter-based)")
        print(f"    delay {faults.delay_ms}ms  "
              f"drop every {faults.drop_every_n}  "
              f"garbage every {faults.garbage_every_n}  "
              f"half-open every {faults.half_open_every_n}")
    print()
    print("  Ctrl+C to stop.")
    # Flush explicitly. serve() then blocks forever, and Python buffers
    # stdout when it is not a tty — so under a supervisor or with the
    # output redirected to a log, the banner would sit in the buffer
    # until shutdown. The banner exists so whoever points a collector at
    # this can confirm their register map is current; delivered at exit
    # it is worthless.
    sys.stdout.flush()

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        modbus.shutdown()
        modbus.server_close()
        http.shutdown()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="loom-shim",
        description="Bench simulator: serve the twin, export its model.")
    parser.add_argument("--program", default=DEFAULT_PROGRAM,
                        help="ST program the twin runs")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="run the twin and serve it")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--modbus-port", type=int, default=5502)
    p_serve.add_argument("--http-port", type=int, default=5174)
    p_serve.add_argument("--max-connections", type=int, default=4)
    p_serve.add_argument("--scan-period-ms", type=int, default=10)
    p_serve.add_argument("--sim-step-ms", type=int, default=1)
    p_serve.add_argument("--fault-delay-ms", type=int, default=0)
    p_serve.add_argument("--fault-drop-every", type=int, default=0)
    p_serve.add_argument("--fault-garbage-every", type=int, default=0)
    p_serve.add_argument("--fault-half-open-every", type=int, default=0)
    p_serve.set_defaults(func=cmd_serve)

    p_export = sub.add_parser("export", help="write the NodeSet2 file")
    p_export.add_argument("--out", default=DEFAULT_NODESET)
    p_export.set_defaults(func=cmd_export)

    p_validate = sub.add_parser("validate", help="validate the model")
    p_validate.add_argument("--out", default=DEFAULT_NODESET)
    p_validate.add_argument("--xsd", default=DEFAULT_XSD)
    p_validate.set_defaults(func=cmd_validate)

    p_map = sub.add_parser("map", help="print the register map")
    p_map.set_defaults(func=cmd_map)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
