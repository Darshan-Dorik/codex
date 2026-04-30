"""
ui/api_server.py — Mock PLC State API Server

Serves GET /state with simulated machine state.
Runs the loom twin simulation in a background loop and exposes
the current state as JSON.

Usage:
    python ui/api_server.py

Endpoint:
    GET http://localhost:5000/state
    Response: {
      "time": int,
      "motor_running": bool,
      "shuttle_position": float,   # 0-360 degrees
      "sensors": { "X0": bool, "X1": bool, "X2": bool },
      "jam_detected": bool
    }
"""

import sys
import os
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src/core"))

from loom_twin import MotorStateMachine, CyclicShuttleModel, PositionSensor

# ---------------------------------------------------------------------------
# Simulation state (shared between sim thread and HTTP handler)
# ---------------------------------------------------------------------------

_state = {
    "time":             0,
    "motor_running":    False,
    "shuttle_position": 0.0,
    "sensors":          {"X0": False, "X1": False, "X2": False},
    "jam_detected":     False
}
_state_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Simulation loop
# ---------------------------------------------------------------------------

def simulation_loop():
    """Run the loom twin in a background thread, updating _state."""
    motor   = MotorStateMachine(startup_delay_ms=300, stop_delay_ms=200)
    shuttle = CyclicShuttleModel(speed_units_per_sec=60.0, cycle_length=360.0)
    sensor  = PositionSensor(threshold=180.0, window=20.0)

    t_ms        = 0
    step_ms     = 100
    jam_at_ms   = None   # will be set after 2 full cycles

    # Start motor
    motor.command(True)

    while True:
        t_ms += step_ms

        # Inject jam after 2 full cycles (~12s), clear after 3s
        if shuttle.cycles_completed >= 2 and jam_at_ms is None:
            jam_at_ms = t_ms

        jam_active = (jam_at_ms is not None and
                      t_ms >= jam_at_ms and
                      t_ms < jam_at_ms + 3000)

        # Motor stops on jam
        if jam_active:
            motor.command(False)
        elif jam_at_ms is not None and t_ms >= jam_at_ms + 3000:
            # Restart after jam clears
            motor.command(True)
            jam_at_ms = None

        motor.update(t_ms)
        shuttle.update(t_ms, motor.is_running)
        sensor_active = sensor.update(shuttle.position)

        with _state_lock:
            _state["time"]             = t_ms
            _state["motor_running"]    = motor.is_running
            _state["shuttle_position"] = round(shuttle.position, 2)
            _state["sensors"]          = {
                "X0": motor.command_on,
                "X1": sensor_active,
                "X2": jam_active
            }
            _state["jam_detected"] = jam_active

        time.sleep(step_ms / 1000.0)

# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class StateHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/state":
            with _state_lock:
                body = json.dumps(_state).encode()
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start simulation in background thread
    sim_thread = threading.Thread(target=simulation_loop, daemon=True)
    sim_thread.start()

    host, port = "localhost", 5174
    server = HTTPServer((host, port), StateHandler)
    print(f"PLC State API running at http://{host}:{port}/state")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
