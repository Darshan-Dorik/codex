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
        # Branch coverage: {"condition_label": {"then": int, "else": int}}
        self.branch_coverage = {}

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

                # --- Branch coverage tracking ---
                if label not in self.branch_coverage:
                    self.branch_coverage[label] = {"then": 0, "else": 0}
                if cond_result:
                    self.branch_coverage[label]["then"] += 1
                else:
                    self.branch_coverage[label]["else"] += 1

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
    from st_parser import parse_st

    print("=" * 60)
    print("Phase 4 - Step 6: Coverage Tracking — Branches")
    print("=" * 60)

    # -------------------------------------------------------
    # Scenario A: IF/ELSE — 4 THEN, 2 ELSE
    # -------------------------------------------------------
    st_a = """
    IF X0 THEN
        Y0 := TRUE;
    ELSE
        Y0 := FALSE;
    END_IF;
    """
    plc_a = PLC()
    plc_a.logic = parse_st(st_a)

    schedule_a = [
        (100, {"X0": True}),   # THEN
        (200, {"X0": False}),  # ELSE
        (300, {"X0": True}),   # THEN
        (400, {"X0": True}),   # THEN
        (500, {"X0": False}),  # ELSE
        (600, {"X0": True}),   # THEN
    ]

    print("\nScenario A — IF X0 THEN Y0:=TRUE ELSE Y0:=FALSE")
    print(f"  {'Time':>6}  {'X0':>5}  {'Branch':>6}")
    print("  " + "-" * 28)
    for t, inputs in schedule_a:
        plc_a.inputs = dict(inputs)
        plc_a.scan(t)
        branch = "THEN" if inputs["X0"] else "ELSE"
        print(f"  {t:>6}ms  {str(inputs['X0']):>5}  {branch:>6}")

    lbl_a = "X0"
    print(f"\n  Branch coverage for '{lbl_a}':")
    print(f"    THEN taken: {plc_a.branch_coverage[lbl_a]['then']}")
    print(f"    ELSE taken: {plc_a.branch_coverage[lbl_a]['else']}")

    # -------------------------------------------------------
    # Scenario B: AND NOT condition — 3 THEN, 3 ELSE
    # (same schedule as Step 5 to cross-verify)
    # -------------------------------------------------------
    st_b = """
    IF X0 AND NOT X1 THEN
        Y0 := TRUE;
    ELSE
        Y0 := FALSE;
    END_IF;
    """
    plc_b = PLC()
    plc_b.logic = parse_st(st_b)

    schedule_b = [
        (100, {"X0": True,  "X1": False}),  # THEN
        (200, {"X0": True,  "X1": True}),   # ELSE
        (300, {"X0": False, "X1": False}),  # ELSE
        (400, {"X0": True,  "X1": False}),  # THEN
        (500, {"X0": True,  "X1": False}),  # THEN
        (600, {"X0": False, "X1": True}),   # ELSE
    ]

    print("\nScenario B — IF X0 AND NOT X1 THEN Y0:=TRUE ELSE Y0:=FALSE")
    print(f"  {'Time':>6}  {'X0':>5}  {'X1':>5}  {'Branch':>6}")
    print("  " + "-" * 34)
    for t, inputs in schedule_b:
        plc_b.inputs = dict(inputs)
        plc_b.scan(t)
        cond = inputs["X0"] and not inputs["X1"]
        branch = "THEN" if cond else "ELSE"
        print(f"  {t:>6}ms  {str(inputs['X0']):>5}  {str(inputs['X1']):>5}  {branch:>6}")

    lbl_b = "(X0 AND NOT(X1))"
    print(f"\n  Branch coverage for '{lbl_b}':")
    print(f"    THEN taken: {plc_b.branch_coverage[lbl_b]['then']}")
    print(f"    ELSE taken: {plc_b.branch_coverage[lbl_b]['else']}")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n  --- Assertions ---")

    assert plc_a.branch_coverage[lbl_a]["then"] == 4, "Scenario A: expected 4 THEN"
    assert plc_a.branch_coverage[lbl_a]["else"] == 2, "Scenario A: expected 2 ELSE"
    print(f"  PASS — Scenario A: then=4, else=2")

    assert plc_b.branch_coverage[lbl_b]["then"] == 3, "Scenario B: expected 3 THEN"
    assert plc_b.branch_coverage[lbl_b]["else"] == 3, "Scenario B: expected 3 ELSE"
    print(f"  PASS — Scenario B: then=3, else=3")

    # Verify branch_coverage and coverage stay in sync
    assert plc_b.branch_coverage[lbl_b]["then"] == plc_b.coverage[lbl_b]["true"]
    assert plc_b.branch_coverage[lbl_b]["else"] == plc_b.coverage[lbl_b]["false"]
    print(f"  PASS — branch_coverage and coverage counts are consistent")
