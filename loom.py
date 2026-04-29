class LoomState:
    def __init__(self):
        self.motor_running = False
        self.shuttle_position = 0.0
        self.jam_detected = False

    def update(self, dt=0.1):
        # Update shuttle position if the motor is running and there's no jam
        if self.motor_running and not self.jam_detected:
            # Assume velocity is 10 units per second for simulation
            self.shuttle_position += 10.0 * dt

if __name__ == "__main__":
    # Test Step 5
    loom = LoomState()
    
    print("Testing Circular Loom State Model (Basic)")
    print(f"Initial state: Motor={loom.motor_running}, Shuttle Pos={loom.shuttle_position}")
    
    loom.motor_running = True
    print("\nMotor turned ON. Simulating 2 seconds...")
    
    for i in range(20): # 2 seconds at 0.1s dt
        loom.update(dt=0.1)
        time_elapsed = round((i + 1) * 0.1, 1)
        shuttle_pos = round(loom.shuttle_position, 1)
        print(f"Time: {time_elapsed}s | Motor: {loom.motor_running} | Shuttle Pos: {shuttle_pos}")
    
    print(f"\nFinal Shuttle Pos: {round(loom.shuttle_position, 1)}")
