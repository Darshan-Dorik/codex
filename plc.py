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


def eval_condition(node, input_snapshot):
    """
    Recursively evaluate a boolean expression tree against an input snapshot.

    Supported node ops:
      {"op": "VAR",  "name": "X0"}           -> input_snapshot.get("X0", False)
      {"op": "NOT",  "operand": <node>}       -> not eval_condition(operand)
      {"op": "AND",  "left": <n>, "right": <n>} -> left and right
      {"op": "OR",   "left": <n>, "right": <n>} -> left or right
    """
    op = node.get("op")
    if op == "VAR":
        return bool(input_snapshot.get(node["name"], False))
    elif op == "NOT":
        return not eval_condition(node["operand"], input_snapshot)
    elif op == "AND":
        return eval_condition(node["left"], input_snapshot) and \
               eval_condition(node["right"], input_snapshot)
    elif op == "OR":
        return eval_condition(node["left"], input_snapshot) or \
               eval_condition(node["right"], input_snapshot)
    else:
        raise ValueError(f"Unknown condition op: '{op}'")


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

        # 2. Store results in output buffer
        output_buffer = dict(self.outputs)

        # 3. Execute logic using snapshot only
        for rule in self.logic:
            # For testing: simulate a mid-scan hardware input change
            if rule.get("id") == "mid_scan_changer":
                self.inputs["X0"] = False
                print("  [Simulate] Physical Input X0 changed to False mid-scan!")
                continue

            rule_type = rule.get("type")

            if rule_type == "if_else":
                # --- New extended ST execution ---
                cond_result = eval_condition(rule["condition"], input_snapshot)
                body = rule["then_body"] if cond_result else rule["else_body"]
                for stmt in body:
                    if stmt["type"] == "set":
                        output_buffer[stmt["target"]] = stmt["value"]

            elif rule_type == "assign":
                # Legacy rule — kept for backward compatibility
                condition_var = rule.get("if")
                target_var = rule.get("set")
                if input_snapshot.get(condition_var, False):
                    output_buffer[target_var] = True
                else:
                    output_buffer[target_var] = False

            elif rule_type == "ton":
                timer_id = rule.get("id")
                condition_var = rule.get("if")
                target_var = rule.get("set")
                pt = rule.get("pt", 1.0)
                if timer_id not in self.timers:
                    self.timers[timer_id] = TON(pt)
                in_state = input_snapshot.get(condition_var, False)
                timer_q = self.timers[timer_id].update(in_state, dt_seconds)
                output_buffer[target_var] = timer_q

            elif rule_type == "interlock":
                run_cond = rule.get("run")
                stop_cond = rule.get("stop")
                target_var = rule.get("set")
                run_state = input_snapshot.get(run_cond, False)
                stop_state = input_snapshot.get(stop_cond, False)
                output_buffer[target_var] = run_state and not stop_state

        # 4. Commit outputs at end
        self.outputs = output_buffer

if __name__ == "__main__":
    import sys, os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from clock import SimulationClock
    from st_parser import parse_st

    print("=" * 60)
    print("Phase 4 - Step 4: Execute Extended ST")
    print("=" * 60)

    def run_case(label, st_code, inputs, expected_outputs):
        plc = PLC()
        plc.logic = parse_st(st_code)
        plc.inputs = dict(inputs)
        plc.scan(100)
        ok = all(plc.outputs.get(k) == v for k, v in expected_outputs.items())
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        print(f"         inputs={inputs} -> outputs={plc.outputs} (expected {expected_outputs})")

    # --- Test 1: simple IF, condition True ---
    run_case(
        "Simple IF — condition True",
        "IF X0 THEN Y0 := TRUE; END_IF;",
        {"X0": True},
        {"Y0": True}
    )

    # --- Test 2: simple IF, condition False, no ELSE ---
    run_case(
        "Simple IF — condition False, no ELSE (Y0 stays unset)",
        "IF X0 THEN Y0 := TRUE; END_IF;",
        {"X0": False},
        {}   # Y0 not written when condition False and no ELSE
    )

    # --- Test 3: IF/ELSE — condition True takes THEN ---
    run_case(
        "IF/ELSE — condition True → THEN branch",
        """
        IF X0 THEN
            Y0 := TRUE;
        ELSE
            Y0 := FALSE;
        END_IF;
        """,
        {"X0": True},
        {"Y0": True}
    )

    # --- Test 4: IF/ELSE — condition False takes ELSE ---
    run_case(
        "IF/ELSE — condition False → ELSE branch",
        """
        IF X0 THEN
            Y0 := TRUE;
        ELSE
            Y0 := FALSE;
        END_IF;
        """,
        {"X0": False},
        {"Y0": False}
    )

    # --- Test 5: AND NOT condition ---
    run_case(
        "AND NOT — X0=True, X1=False → Y0=True",
        """
        IF X0 AND NOT X1 THEN
            Y0 := TRUE;
        ELSE
            Y0 := FALSE;
        END_IF;
        """,
        {"X0": True, "X1": False},
        {"Y0": True}
    )

    run_case(
        "AND NOT — X0=True, X1=True → Y0=False (ELSE)",
        """
        IF X0 AND NOT X1 THEN
            Y0 := TRUE;
        ELSE
            Y0 := FALSE;
        END_IF;
        """,
        {"X0": True, "X1": True},
        {"Y0": False}
    )

    # --- Test 6: Multiple outputs in THEN ---
    run_case(
        "Multiple outputs — X0=True → Y0=True, Y1=True",
        """
        IF X0 THEN
            Y0 := TRUE;
            Y1 := TRUE;
        ELSE
            Y0 := FALSE;
            Y1 := FALSE;
        END_IF;
        """,
        {"X0": True},
        {"Y0": True, "Y1": True}
    )

    run_case(
        "Multiple outputs — X0=False → Y0=False, Y1=False",
        """
        IF X0 THEN
            Y0 := TRUE;
            Y1 := TRUE;
        ELSE
            Y0 := FALSE;
            Y1 := FALSE;
        END_IF;
        """,
        {"X0": False},
        {"Y0": False, "Y1": False}
    )

    # --- Test 7: OR condition ---
    run_case(
        "OR — X0=False, X2=True → Y0=True",
        """
        IF X0 OR X2 THEN
            Y0 := TRUE;
        ELSE
            Y0 := FALSE;
        END_IF;
        """,
        {"X0": False, "X2": True},
        {"Y0": True}
    )
