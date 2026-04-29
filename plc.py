class TON:
    def __init__(self, pt):
        self.pt = pt  # Preset time
        self.et = 0.0 # Elapsed time
        self.q = False # Output
        self.in_state = False # Input

    def update(self, in_state, dt):
        self.in_state = in_state
        if not self.in_state:
            self.et = 0.0
            self.q = False
        else:
            self.et += dt
            if self.et >= self.pt:
                self.q = True
        return self.q

class PLC:
    def __init__(self):
        self.inputs = {}
        self.outputs = {}
        self.logic = []
        self.timers = {}

    def scan(self, dt=0.1):
        # 1. Take input snapshot
        input_snapshot = dict(self.inputs)
        
        # 3. Store results in output buffer
        output_buffer = dict(self.outputs)

        # 2. Execute logic using snapshot only
        for rule in self.logic:
            # For testing: simulate a mid-scan hardware input change
            if rule.get("id") == "mid_scan_changer":
                self.inputs["X0"] = False
                print("  [Simulate] Physical Input X0 changed to False mid-scan!")
                continue

            if rule.get("type") == "assign":
                condition_var = rule.get("if")
                target_var = rule.get("set")
                
                if input_snapshot.get(condition_var, False):
                    output_buffer[target_var] = True
                else:
                    output_buffer[target_var] = False
            elif rule.get("type") == "ton":
                timer_id = rule.get("id")
                condition_var = rule.get("if")
                target_var = rule.get("set")
                pt = rule.get("pt", 1.0)
                
                if timer_id not in self.timers:
                    self.timers[timer_id] = TON(pt)
                
                in_state = input_snapshot.get(condition_var, False)
                timer_q = self.timers[timer_id].update(in_state, dt)
                output_buffer[target_var] = timer_q
            elif rule.get("type") == "interlock":
                run_cond = rule.get("run")
                stop_cond = rule.get("stop")
                target_var = rule.get("set")
                
                run_state = input_snapshot.get(run_cond, False)
                stop_state = input_snapshot.get(stop_cond, False)
                output_buffer[target_var] = run_state and not stop_state

        # 4. Commit outputs at end
        self.outputs = output_buffer

if __name__ == "__main__":
    print("Phase 2 - Step 2: Output Buffer Isolation Test\n")
    
    plc = PLC()
    
    # Multiple rules writing to the same output (Y0)
    plc.logic = [
        {"type": "assign", "if": "X0", "set": "Y0"}, # Rule A
        {"type": "assign", "if": "X1", "set": "Y0"}  # Rule B (executes last)
    ]
    
    # Case 1: X0=True, X1=False -> Y0 should be False
    plc.inputs["X0"] = True
    plc.inputs["X1"] = False
    plc.scan()
    print(f"Test 1 Inputs: X0={plc.inputs['X0']}, X1={plc.inputs['X1']}")
    print(f"Test 1 Outputs: Y0={plc.outputs.get('Y0')} (Expected: False)")
    
    # Case 2: X0=False, X1=True -> Y0 should be True
    plc.inputs["X0"] = False
    plc.inputs["X1"] = True
    plc.scan()
    print(f"\nTest 2 Inputs: X0={plc.inputs['X0']}, X1={plc.inputs['X1']}")
    print(f"Test 2 Outputs: Y0={plc.outputs.get('Y0')} (Expected: True)")
