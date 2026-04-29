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


def condition_label(node):
    """
    Convert a condition expression tree into a stable human-readable string.
    Used as the key for coverage tracking.

    Examples:
      {"op": "VAR", "name": "X0"}          -> "X0"
      {"op": "NOT", "operand": VAR X1}     -> "NOT(X1)"
      {"op": "AND", left: X0, right: X1}   -> "(X0 AND X1)"
      {"op": "OR",  left: X0, right: X2}   -> "(X0 OR X2)"
    """
    op = node.get("op")
    if op == "VAR":
        return node["name"]
    elif op == "NOT":
        return f"NOT({condition_label(node['operand'])})"
    elif op == "AND":
        return f"({condition_label(node['left'])} AND {condition_label(node['right'])})"
    elif op == "OR":
        return f"({condition_label(node['left'])} OR {condition_label(node['right'])})"
    else:
        return f"UNKNOWN({op})"


class PLC:
    def __init__(self):
        self.inputs = {}
        self.outputs = {}
        self.logic = []
        self.timers = {}
        self.last_scan_time_ms = 0
        # Coverage tracking: {"condition_label": {"true": int, "false": int}}
        self.coverage = {}

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

                # --- Coverage tracking ---
                label = condition_label(rule["condition"])
                if label not in self.coverage:
                    self.coverage[label] = {"true": 0, "false": 0}
                if cond_result:
                    self.coverage[label]["true"] += 1
                else:
                    self.coverage[label]["false"] += 1

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
    print("Phase 4 - Step 5: Coverage Tracking — Conditions")
    print("=" * 60)

    st_code = """
    IF X0 AND NOT X1 THEN
        Y0 := TRUE;
    ELSE
        Y0 := FALSE;
    END_IF;
    """

    plc = PLC()
    plc.logic = parse_st(st_code)
    clock = SimulationClock()

    # 6 scan cycles with varying inputs:
    #   t=100: X0=T, X1=F  -> condition TRUE
    #   t=200: X0=T, X1=T  -> condition FALSE
    #   t=300: X0=F, X1=F  -> condition FALSE
    #   t=400: X0=T, X1=F  -> condition TRUE
    #   t=500: X0=T, X1=F  -> condition TRUE
    #   t=600: X0=F, X1=T  -> condition FALSE

    schedule = [
        (100, {"X0": True,  "X1": False}),
        (200, {"X0": True,  "X1": True}),
        (300, {"X0": False, "X1": False}),
        (400, {"X0": True,  "X1": False}),
        (500, {"X0": True,  "X1": False}),
        (600, {"X0": False, "X1": True}),
    ]

    print(f"\n  Logic: {st_code.strip()}\n")
    print(f"  {'Time':>6}  {'X0':>5}  {'X1':>5}  {'Y0':>5}  {'Cond':>6}")
    print("  " + "-" * 40)

    for t, inputs in schedule:
        plc.inputs = dict(inputs)
        plc.scan(t)
        y0   = plc.outputs.get("Y0", "-")
        cond = "TRUE" if y0 is True else "FALSE"
        print(f"  {t:>6}ms  {str(inputs['X0']):>5}  {str(inputs['X1']):>5}  "
              f"{str(y0):>5}  {cond}")

    # --- Print coverage stats ---
    print("\n  --- Condition Coverage ---")
    for lbl, counts in plc.coverage.items():
        total = counts["true"] + counts["false"]
        print(f"  Condition : {lbl}")
        print(f"    TRUE    : {counts['true']} / {total}")
        print(f"    FALSE   : {counts['false']} / {total}")

    # --- Assertions ---
    print("\n  --- Assertions ---")
    lbl = "(X0 AND NOT(X1))"
    assert lbl in plc.coverage,                   f"Label '{lbl}' not found"
    assert plc.coverage[lbl]["true"]  == 3,       "Expected 3 TRUE evaluations"
    assert plc.coverage[lbl]["false"] == 3,       "Expected 3 FALSE evaluations"
    print(f"  PASS — '{lbl}': true=3, false=3")
