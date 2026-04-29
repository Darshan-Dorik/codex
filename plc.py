class PLC:
    def __init__(self):
        self.inputs = {}
        self.outputs = {}

    def scan(self):
        # Hardcoded logic: IF X0 THEN Y0 = TRUE
        if self.inputs.get("X0", False):
            self.outputs["Y0"] = True
        else:
            self.outputs["Y0"] = False

if __name__ == "__main__":
    # Test Step 2
    plc = PLC()
    
    # Test 1: X0 = True
    print("Test 1: X0 = True")
    plc.inputs["X0"] = True
    plc.scan()
    print(f"  Inputs:  {plc.inputs}")
    print(f"  Outputs: {plc.outputs}")
    
    # Test 2: X0 = False
    print("\nTest 2: X0 = False")
    plc.inputs["X0"] = False
    plc.scan()
    print(f"  Inputs:  {plc.inputs}")
    print(f"  Outputs: {plc.outputs}")
