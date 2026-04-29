import json

def build_llm_payload(current_state, logic, recent_logs):
    """
    Builds a structured JSON payload for the LLM interface.
    """
    payload = {
        "system_state": current_state,
        "plc_logic_ast": logic,
        "execution_telemetry": recent_logs
    }
    return json.dumps(payload, indent=2)

if __name__ == "__main__":
    print("Phase 2 - Step 10: Prepare LLM Interface Test\n")
    
    # 1. Dummy State
    dummy_state = {
        "motor_running": False,
        "shuttle_position": 2.0,
        "jam_detected": True
    }
    
    # 2. Dummy Logic (AST)
    dummy_logic = [
        {"type": "assign", "if": "X0", "set": "Y0"}
    ]
    
    # 3. Dummy Telemetry (Recent Logs)
    dummy_logs = [
        {
            "time": 200, 
            "plc": {"inputs": {"X0": True}, "outputs": {"Y0": True}}, 
            "loom": {"motor_running": True, "shuttle_position": 2.0, "jam_detected": False}
        },
        {
            "time": 300, 
            "plc": {"inputs": {"X0": False}, "outputs": {"Y0": False}}, 
            "loom": {"motor_running": False, "shuttle_position": 2.0, "jam_detected": True}
        }
    ]
    
    payload_json = build_llm_payload(dummy_state, dummy_logic, dummy_logs)
    
    print("--- Generated JSON Payload for LLM ---")
    print(payload_json)
