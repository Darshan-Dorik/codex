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
        self.last_scan_time_ms = 0

    def scan(self, current_time_ms):
        # Calculate delta time in seconds for timers
        dt_seconds = (current_time_ms - self.last_scan_time_ms) / 1000.0
        self.last_scan_time_ms = current_time_ms
        
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
                timer_q = self.timers[timer_id].update(in_state, dt_seconds)
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
    import sys
    import os
    # Add current dir to path to import clock
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from clock import SimulationClock
    
    print("Phase 2 - Step 4: Time-Aware PLC Scan Test\n")
    
    plc = PLC()
    clock = SimulationClock()
    
    print(f"Initial PLC last_scan_time: {plc.last_scan_time_ms} ms")
    
    clock.advance(100)
    print(f"\nAdvancing clock by 100 ms -> Clock Time: {clock.get_time()} ms")
    plc.scan(clock.get_time())
    print(f"PLC last_scan_time updated to: {plc.last_scan_time_ms} ms")
    
    clock.advance(50)
    print(f"\nAdvancing clock by 50 ms -> Clock Time: {clock.get_time()} ms")
    plc.scan(clock.get_time())
    print(f"PLC last_scan_time updated to: {plc.last_scan_time_ms} ms")
