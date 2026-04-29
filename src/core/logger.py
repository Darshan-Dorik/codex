import json

class SystemLogger:
    def __init__(self):
        self.logs = []

    def log_cycle(self, timestamp, plc_inputs, plc_outputs, loom_state):
        entry = {
            "time": timestamp,
            "plc": {
                "inputs": dict(plc_inputs),
                "outputs": dict(plc_outputs)
            },
            "loom": {
                "motor_running": loom_state.motor_running,
                "shuttle_position": round(loom_state.shuttle_position, 2),
                "jam_detected": loom_state.jam_detected
            }
        }
        self.logs.append(entry)

    def print_logs(self):
        print(json.dumps(self.logs, indent=2))
