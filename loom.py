class LoomState:
    def __init__(self):
        self.motor_running = False
        self.shuttle_position = 0.0
        self.jam_detected = False
        self.last_update_time_ms = 0

    def update(self, current_time_ms):
        # Calculate time delta in seconds
        dt_seconds = (current_time_ms - self.last_update_time_ms) / 1000.0
        self.last_update_time_ms = current_time_ms
        
        # Update shuttle position if the motor is running and there's no jam
        if self.motor_running and not self.jam_detected:
            # Assume velocity is 10 units per second for simulation
            self.shuttle_position += 10.0 * dt_seconds

if __name__ == "__main__":
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from clock import SimulationClock
    
    print("Phase 2 - Step 6: Event-Driven Loom Update Test\n")
    
    loom = LoomState()
    clock = SimulationClock()
    
    print(f"Initial state: Motor={loom.motor_running}, Shuttle Pos={loom.shuttle_position}")
    
    loom.motor_running = True
    print("Motor turned ON. Simulating 3 intervals of 500ms...")
    
    for i in range(3):
        clock.advance(500)
        loom.update(clock.get_time())
        
        t_ms = clock.get_time()
        pos = round(loom.shuttle_position, 1)
        print(f"Clock: {t_ms}ms | Shuttle Pos: {pos}")
