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

def test_step7():
    plc = PLC()
    loom = LoomState()
    
    print("\nTesting Step 7: Connect Loom -> PLC Inputs")
    print("Simulating shuttle position crossing threshold (15.0)\n")
    
    threshold = 15.0
    loom.motor_running = True
    
    for i in range(20): # Simulate 2.0 seconds
        loom.update(dt=0.1)
        
        # Connect Loom -> PLC Input
        if loom.shuttle_position > threshold:
            plc.inputs["X1"] = True
        else:
            plc.inputs["X1"] = False
            
        time_elapsed = round((i + 1) * 0.1, 1)
        pos = round(loom.shuttle_position, 1)
        x1 = plc.inputs.get("X1", False)
        print(f"Time: {time_elapsed}s | Shuttle Pos: {pos} | PLC Input X1: {x1}")

def test_step8():
    plc = PLC()
    loom = LoomState()
    
    # Logic: Run motor if X0 is True, BUT stop if Jam (X2) is True
    plc.logic = [
        {"type": "interlock", "run": "X0", "stop": "X2", "set": "Y0"}
    ]
    
    print("\nTesting Step 8: Fault Injection (Jam Condition)")
    
    plc.inputs["X0"] = True # Start command
    plc.inputs["X2"] = False # No jam initially
    
    for i in range(15):
        # Inject Fault at t = 0.5s
        if i == 5:
            print(">>> INJECTING JAM FAULT! <<<")
            loom.jam_detected = True
            
        # Connect Loom Sensors -> PLC
        # If loom is jammed, PLC sensor X2 detects it
        if loom.jam_detected:
            plc.inputs["X2"] = True
            
        # Scan PLC
        plc.scan(dt=0.1)
        
        # Connect PLC -> Loom
        loom.motor_running = plc.outputs.get("Y0", False)
        
        # Update Loom
        loom.update(dt=0.1)
        
        time_elapsed = round((i + 1) * 0.1, 1)
        pos = round(loom.shuttle_position, 1)
        y0 = plc.outputs.get("Y0")
        print(f"Time: {time_elapsed}s | Jam: {loom.jam_detected} | PLC Y0: {y0} | Shuttle Pos: {pos}")

from logger import SystemLogger

def test_step9():
    plc = PLC()
    loom = LoomState()
    logger = SystemLogger()
    
    plc.logic = [
        {"type": "interlock", "run": "X0", "stop": "X2", "set": "Y0"}
    ]
    
    print("\nTesting Step 9: Structured Logging System")
    
    plc.inputs["X0"] = True
    plc.inputs["X2"] = False
    
    for i in range(5): # Simulate just 5 cycles to keep logs readable
        if i == 3:
            loom.jam_detected = True
            
        if loom.jam_detected:
            plc.inputs["X2"] = True
            
        plc.scan(dt=0.1)
        loom.motor_running = plc.outputs.get("Y0", False)
        loom.update(dt=0.1)
        
        time_elapsed = round((i + 1) * 0.1, 1)
        
        # Log the state
        logger.log_cycle(time_elapsed, plc.inputs, plc.outputs, loom)
        
    print("\n--- Structured Logs ---")
    logger.print_logs()

def test_phase2_step8():
    from st_parser import parse_st
    from clock import SimulationClock
    
    print("\nPhase 2 - Step 8: Execute Parsed ST")
    
    st_code = """
    IF X0 THEN
        Y0 := TRUE;
    END_IF;
    """
    
    print("1. Raw ST Code:")
    print(st_code.strip())
    
    plc = PLC()
    clock = SimulationClock()
    
    # 2. Parse ST to DSL
    parsed_logic = parse_st(st_code)
    plc.logic = parsed_logic
    print(f"\n2. Parsed Logic Assigned to PLC: {plc.logic}")
    
    # 3. Execute in PLC
    print("\n3. Executing in PLC Engine")
    
    # Test True
    plc.inputs["X0"] = True
    plc.scan(clock.get_time())
    print(f"  Input X0={plc.inputs['X0']} -> Output Y0={plc.outputs.get('Y0')} (Expected: True)")
    
    # Test False
    clock.advance(100)
    plc.inputs["X0"] = False
    plc.scan(clock.get_time())
    print(f"  Input X0={plc.inputs['X0']} -> Output Y0={plc.outputs.get('Y0')} (Expected: False)")

def test_phase2_step9():
    from logger import SystemLogger
    from plc import PLC
    from loom import LoomState
    from clock import SimulationClock
    from st_parser import parse_st
    
    print("\nPhase 2 - Step 9: Logging with Time Context")
    
    plc = PLC()
    loom = LoomState()
    logger = SystemLogger()
    clock = SimulationClock()
    
    st_code = """
    IF X0 THEN
        Y0 := TRUE;
    END_IF;
    """
    plc.logic = parse_st(st_code)
    
    plc.inputs["X0"] = True
    loom.motor_running = False
    
    for i in range(5):
        clock.advance(100) # 100ms per scan cycle
        current_time_ms = clock.get_time()
        
        # Simulate Jam at 300ms
        if current_time_ms == 300:
            loom.jam_detected = True
            
        if loom.jam_detected:
            plc.inputs["X0"] = False # Interlock triggering stop
            
        plc.scan(current_time_ms)
        loom.motor_running = plc.outputs.get("Y0", False)
        loom.update(current_time_ms)
        
        # Log the state using exact global clock time
        logger.log_cycle(current_time_ms, plc.inputs, plc.outputs, loom)
        
    print("\n--- Structured Logs (Phase 2 Time-Aware) ---")
    logger.print_logs()

if __name__ == "__main__":
    test_phase2_step9()
