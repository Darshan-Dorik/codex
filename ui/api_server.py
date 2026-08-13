"""
ui/api_server.py — Machine State API Server

Serves GET /state with the loom twin's current state, for the React
dashboard.

This is now a thin HTTP frontend over src/shim/twin_runtime.TwinRuntime.
It owns no simulation of its own: the runtime holds the only mutable
state and hands out immutable snapshots, so this handler, the Modbus
server and anything else read the SAME scan.

Usage:
    python ui/api_server.py

Endpoint:
    GET http://localhost:5174/state
    Response: {
      "time": int,                 # ms, PLC scan time
      "motor_running": bool,
      "shuttle_position": float,   # 0-360 degrees
      "sensors": { "X0": bool, "X1": bool, "X2": bool },
      "jam_detected": bool,

      # additive — the dashboard reads the five keys above
      "outputs": { "Y0": bool, "Y1": bool },
      "motor_state": str,          # STOPPED|STARTING|RUNNING|STOPPING
      "scan_count": int,
      "cycles_completed": int
    }

WHAT CHANGED, AND WHY IT IS NOT A BUG
-------------------------------------
This server used to run the twin OPEN-loop: it commanded the motor
directly and injected a jam on a timer, with no PLC anywhere. Two
visible behaviours changed when the PLC went into the loop. Both are
intended. See ui/README.md.

  1. X0 STAYS TRUE DURING A JAM.
     Previously the jam was implemented by dropping X0 — the run
     command itself. That is not what a jam is. X0 is the operator's
     run command and nothing about a jam withdraws it. Now X2 (jam)
     rises, the PLC evaluates Y0 := X0 AND NOT X2, and Y0 falls.

  2. THE MOTOR READS "RUNNING" FOR ONE MORE SCAN AFTER THE JAM.
     Y0 falls in the same scan X2 is sampled, so the logic adds no
     latency. But that scan's physics already ran before the scan
     committed the new command, so motor_running is still True in the
     snapshot and turns over on the next one — 10ms at the default
     scan period.
"""

import os
import sys
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("", "src/core", "src/shim"):
    _p = os.path.join(_ROOT, _sub) if _sub else _ROOT
    if _p not in sys.path:
        sys.path.insert(0, _p)

from twin_runtime import make_runtime

# The runtime is created at startup and read-only from here on.
_runtime = None


class StateHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/state":
            body = json.dumps(_runtime.snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        pass   # suppress request logs


if __name__ == "__main__":
    _runtime = make_runtime()
    _runtime.start_thread()

    host, port = "localhost", 5174
    server = HTTPServer((host, port), StateHandler)
    print(f"Machine State API running at http://{host}:{port}/state")
    print(f"  program      : {_runtime.program}")
    print(f"  scan period  : {_runtime.scan_period_ms}ms")
    print(f"  physics step : {_runtime.sim_step_ms}ms "
          f"({_runtime.rate_ratio}:1)")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
