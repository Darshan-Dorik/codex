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
        # Interpret structured logic (Mini DSL)
        for rule in self.logic:
            if rule.get("type") == "assign":
                condition_var = rule.get("if")
                target_var = rule.get("set")
                
                if self.inputs.get(condition_var, False):
                    self.outputs[target_var] = True
                else:
                    self.outputs[target_var] = False
            elif rule.get("type") == "ton":
                timer_id = rule.get("id")
                condition_var = rule.get("if")
                target_var = rule.get("set")
                pt = rule.get("pt", 1.0)
                
                if timer_id not in self.timers:
                    self.timers[timer_id] = TON(pt)
                
                in_state = self.inputs.get(condition_var, False)
                timer_q = self.timers[timer_id].update(in_state, dt)
                self.outputs[target_var] = timer_q
            elif rule.get("type") == "interlock":
                run_cond = rule.get("run")
                stop_cond = rule.get("stop")
                target_var = rule.get("set")
                
                run_state = self.inputs.get(run_cond, False)
                stop_state = self.inputs.get(stop_cond, False)
                self.outputs[target_var] = run_state and not stop_state

if __name__ == "__main__":
    # Test Step 4
    plc = PLC()
    
    # Define logic using DSL (TON Timer)
    plc.logic = [
        {"type": "ton", "id": "T0", "if": "X0", "pt": 1.0, "set": "Y0"}
    ]
    
    print("Testing TON Timer: PT = 1.0s, Input = X0, Output = Y0\n")
    
    # Test TON
    plc.inputs["X0"] = True
    for i in range(15):
        plc.scan(dt=0.1)
        # Handle floating point inaccuracies for clean output
        time_elapsed = round((i + 1) * 0.1, 1)
        et = round(plc.timers["T0"].et, 1)
        print(f"Time: {time_elapsed}s | IN: {plc.inputs['X0']} | ET: {et}s | Q (Y0): {plc.outputs.get('Y0', False)}")
