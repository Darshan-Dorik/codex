from plc import PLC
from loom import LoomState

def test_step6():
    plc = PLC()
    loom = LoomState()
    
    # Logic: IF X0 THEN Y0 = TRUE
    plc.logic = [
        {"type": "assign", "if": "X0", "set": "Y0"}
    ]
    
    print("Testing Step 6: Connect PLC Outputs -> Loom")
    
    print(f"Initial Loom Motor State: {loom.motor_running}")
    
    # 1. Trigger X0
    print("\nSetting PLC input X0 = True")
    plc.inputs["X0"] = True
    
    # 2. Scan PLC
    plc.scan(dt=0.1)
    
    # 3. Connect PLC Output (Y0) to Loom (motor_running)
    loom.motor_running = plc.outputs.get("Y0", False)
    
    # 4. Verify motor starts
    print(f"PLC Output Y0: {plc.outputs.get('Y0')}")
    print(f"Loom Motor Running: {loom.motor_running}")
    
    # Simulate a little bit of time to ensure it works
    loom.update(dt=0.1)
    print(f"Loom Shuttle Pos after 0.1s: {loom.shuttle_position:.1f}")

if __name__ == "__main__":
    test_step6()
