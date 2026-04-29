class PLC:
    def __init__(self):
        self.inputs = {}
        self.outputs = {}

    def scan(self):
        pass

if __name__ == "__main__":
    # Initialize PLC
    plc = PLC()
    
    # Set input X0 = True
    plc.inputs["X0"] = True
    
    # Print state
    print("PLC State:")
    print(f"  Inputs:  {plc.inputs}")
    print(f"  Outputs: {plc.outputs}")
