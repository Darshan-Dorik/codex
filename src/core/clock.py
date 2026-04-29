class SimulationClock:
    def __init__(self):
        self.time_ms = 0

    def advance(self, delta_ms):
        if delta_ms < 0:
            raise ValueError("Time cannot go backwards")
        self.time_ms += delta_ms

    def get_time(self):
        return self.time_ms

if __name__ == "__main__":
    print("Phase 2 - Step 3: Global Clock Test\n")
    
    clock = SimulationClock()
    print(f"Initial Time: {clock.get_time()} ms")
    
    print("Advancing time by 100 ms...")
    clock.advance(100)
    print(f"Current Time: {clock.get_time()} ms")
    
    print("Advancing time by 50 ms...")
    clock.advance(50)
    print(f"Current Time: {clock.get_time()} ms")
