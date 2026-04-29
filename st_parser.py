import re
import json

def parse_st(st_code):
    """
    Parses minimal Structured Text:
    IF <var> THEN <var> := TRUE/FALSE;
    END_IF;
    """
    logic = []
    
    # Regex to match: IF <cond> THEN <target> := TRUE/FALSE; END_IF;
    pattern = re.compile(r"IF\s+(.+?)\s+THEN\s+(.+?)\s*:=\s*(TRUE|FALSE)\s*;\s*END_IF;", re.IGNORECASE | re.DOTALL)
    
    matches = pattern.findall(st_code)
    for match in matches:
        cond_var = match[0].strip()
        target_var = match[1].strip()
        val = match[2].strip().upper()
        
        # We map this to our internal 'assign' engine rule.
        # Note: Our 'assign' rule currently evaluates as a continuous coil
        # (setting to True if condition is met, False otherwise).
        if val == "TRUE":
            logic.append({
                "type": "assign",
                "if": cond_var,
                "set": target_var
            })
            
    return logic

if __name__ == "__main__":
    print("Phase 2 - Step 7: Basic ST Parser Test\n")
    
    st_input = """
    IF X0 THEN
        Y0 := TRUE;
    END_IF;
    """
    
    print("Input ST String:")
    print(st_input.strip())
    
    parsed_logic = parse_st(st_input)
    
    print("\nParsed Internal Representation:")
    print(json.dumps(parsed_logic, indent=2))
