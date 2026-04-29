import json

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
    print("Phase 3 - Step 1: Scenario Data Structure Test\n")
    
    scenario = create_example_scenario()
    
    print("Parsed Scenario Structure:")
    print(json.dumps(scenario, indent=2))
