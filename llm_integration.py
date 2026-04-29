import json

def generate_ollama_prompt(logic, final_state, logs):
    """
    Format the logic, state, and logs into a structured prompt for Ollama.
    (No API implementation yet, only structure as requested)
    """
    prompt = f"""You are an AI diagnostic assistant for a digital twin PLC system.
Below is the system configuration, the logical rules, and the execution logs.

### 1. PLC Logic Rules (DSL)
```json
{json.dumps(logic, indent=2)}
```

### 2. Final System State
```json
{json.dumps(final_state, indent=2)}
```

### 3. Execution Logs (Telemetry)
```json
{json.dumps(logs, indent=2)}
```

---
Task:
Please analyze the execution logs and identify if any fault (e.g., jam) occurred. 
Determine when it occurred, and verify if the PLC logic reacted correctly to stop the motor.
"""
    return prompt

if __name__ == "__main__":
    # Test Step 10 Structure
    dummy_logic = [{"type": "interlock", "run": "X0", "stop": "X2", "set": "Y0"}]
    dummy_state = {"motor_running": False, "shuttle_position": 5.0, "jam_detected": True}
    dummy_logs = [
        {
            "time": 0.4, 
            "plc": {"inputs": {"X0": True, "X2": False}, "outputs": {"Y0": True}}, 
            "loom": {"motor_running": True, "shuttle_position": 4.0, "jam_detected": False}
        },
        {
            "time": 0.5, 
            "plc": {"inputs": {"X0": True, "X2": True}, "outputs": {"Y0": False}}, 
            "loom": {"motor_running": False, "shuttle_position": 4.0, "jam_detected": True}
        }
    ]
    
    print("Testing Step 10: Ollama Prompt Generation Structure\n")
    prompt = generate_ollama_prompt(dummy_logic, dummy_state, dummy_logs)
    print("--- Generated Prompt ---")
    print(prompt)
