import json
from plc import PLC
from loom import LoomState
from clock import SimulationClock

class TestHarness:
    def __init__(self):
        self.plc = None
        self.loom = None
        self.clock = None
        self.scenario = None

    def load_scenario(self, scenario):
        self.scenario = scenario

    def run(self, max_time_ms=1000, step_ms=100):
        print(f"--- Running Scenario: {self.scenario['name']} ---")
        
        self.plc = PLC()
        self.loom = LoomState()
        self.clock = SimulationClock()
        
        # Apply initial inputs
        initial_inputs = self.scenario.get("initial_inputs", {})
        for k, v in initial_inputs.items():
            self.plc.inputs[k] = v
            
        print(f"Initial inputs applied: {self.plc.inputs}")
        
        events = self.scenario.get("events", [])
        
        # Run simulation over time
        while self.clock.get_time() < max_time_ms:
            self.clock.advance(step_ms)
            current_time = self.clock.get_time()
            
            # 1. Process Event Injections (BEFORE Scan)
            for event in events:
                if event["time"] == current_time:
                    print(f"  [Event] At {current_time}ms: Injecting {event['inputs']}")
                    for k, v in event["inputs"].items():
                        self.plc.inputs[k] = v
            
            # 2. Scan PLC
            self.plc.scan(current_time)
            
            # Simple fixed wiring for test harness
            if "Y0" in self.plc.outputs:
                self.loom.motor_running = self.plc.outputs["Y0"]
            
            # 3. Update Loom
            self.loom.update(current_time)
            
            print(f"Time: {current_time}ms | PLC Inputs: {self.plc.inputs} | PLC Outputs: {self.plc.outputs}")

def create_example_scenario():
    scenario = {
        "name": "Simple Motor Start",
        "initial_inputs": {
            "X0": False
        },
        "events": [
            {"time": 500, "inputs": {"X0": True}}
        ],
        "expected": [
            {"time": 600, "outputs": {"Y0": True}}
        ]
    }
    return scenario

if __name__ == "__main__":
    print("Phase 3 - Step 3: Event Injection System Test\n")
    
    scenario = create_example_scenario()
    
    harness = TestHarness()
    harness.load_scenario(scenario)
    
    # Run simple scenario (No logic loaded yet, just verify time progression)
    harness.run(max_time_ms=500, step_ms=100)
