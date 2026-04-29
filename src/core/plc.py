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

    def get_coverage_report(self):
        """
        Produce a structured coverage report dict.

        Schema:
          {
            "conditions": {
              "<label>": {
                "true":  int,   # times condition evaluated True
                "false": int,   # times condition evaluated False
                "total": int,
                "true_pct":  float,  # percentage 0-100
                "false_pct": float
              }
            },
            "branches": {
              "<label>": {
                "then":      int,   # times THEN branch executed
                "else":      int,   # times ELSE branch executed
                "total":     int,
                "then_pct":  float,
                "else_pct":  float,
                "both_covered": bool  # True only if both then>0 and else>0
              }
            }
          }
        """
        report = {"conditions": {}, "branches": {}}

        for label, counts in self.coverage.items():
            total = counts["true"] + counts["false"]
            report["conditions"][label] = {
                "true":      counts["true"],
                "false":     counts["false"],
                "total":     total,
                "true_pct":  round(counts["true"]  / total * 100, 1) if total else 0.0,
                "false_pct": round(counts["false"] / total * 100, 1) if total else 0.0,
            }

        for label, counts in self.branch_coverage.items():
            total = counts["then"] + counts["else"]
            report["branches"][label] = {
                "then":         counts["then"],
                "else":         counts["else"],
                "total":        total,
                "then_pct":     round(counts["then"] / total * 100, 1) if total else 0.0,
                "else_pct":     round(counts["else"] / total * 100, 1) if total else 0.0,
                "both_covered": counts["then"] > 0 and counts["else"] > 0,
            }

        return report

if __name__ == "__main__":
    import sys, os, json
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from st_parser import parse_st

    print("=" * 60)
    print("Phase 4 - Step 7: Coverage Report")
    print("=" * 60)

    # Two IF blocks in one program — each gets its own coverage entry
    st_code = """
    IF X0 AND NOT X1 THEN
        Y0 := TRUE;
    ELSE
        Y0 := FALSE;
    END_IF;

    IF X2 OR X3 THEN
        Y1 := TRUE;
    ELSE
        Y1 := FALSE;
    END_IF;
    """

    plc = PLC()
    plc.logic = parse_st(st_code)

    # 8 scan cycles — exercise both conditions in different combinations
    schedule = [
        (100, {"X0": True,  "X1": False, "X2": False, "X3": False}),  # cond1=T, cond2=F
        (200, {"X0": True,  "X1": True,  "X2": True,  "X3": False}),  # cond1=F, cond2=T
        (300, {"X0": False, "X1": False, "X2": False, "X3": True}),   # cond1=F, cond2=T
        (400, {"X0": True,  "X1": False, "X2": True,  "X3": True}),   # cond1=T, cond2=T
        (500, {"X0": False, "X1": True,  "X2": False, "X3": False}),  # cond1=F, cond2=F
        (600, {"X0": True,  "X1": False, "X2": False, "X3": False}),  # cond1=T, cond2=F
        (700, {"X0": True,  "X1": True,  "X2": True,  "X3": False}),  # cond1=F, cond2=T
        (800, {"X0": False, "X1": False, "X2": False, "X3": False}),  # cond1=F, cond2=F
    ]

    for t, inputs in schedule:
        plc.inputs = dict(inputs)
        plc.scan(t)

    # --- Get structured report ---
    report = plc.get_coverage_report()

    print("\n--- Coverage Report (JSON) ---")
    print(json.dumps(report, indent=2))

    # --- Human-readable summary ---
    print("\n--- Coverage Summary ---")
    for label, data in report["conditions"].items():
        print(f"  Condition : {label}")
        print(f"    Evaluated TRUE  : {data['true']:>3} / {data['total']}  ({data['true_pct']}%)")
        print(f"    Evaluated FALSE : {data['false']:>3} / {data['total']}  ({data['false_pct']}%)")

    print()
    for label, data in report["branches"].items():
        covered = "FULL" if data["both_covered"] else "PARTIAL"
        print(f"  Branch    : {label}  [{covered}]")
        print(f"    THEN taken : {data['then']:>3} / {data['total']}  ({data['then_pct']}%)")
        print(f"    ELSE taken : {data['else']:>3} / {data['total']}  ({data['else_pct']}%)")

    # --- Assertions ---
    print("\n--- Assertions ---")
    lbl1 = "(X0 AND NOT(X1))"
    lbl2 = "(X2 OR X3)"

    assert lbl1 in report["conditions"],                        f"Missing condition: {lbl1}"
    assert lbl2 in report["conditions"],                        f"Missing condition: {lbl2}"
    assert report["conditions"][lbl1]["true"]  == 3,            "cond1 true count"
    assert report["conditions"][lbl1]["false"] == 5,            "cond1 false count"
    assert report["conditions"][lbl2]["true"]  == 4,            "cond2 true count"
    assert report["conditions"][lbl2]["false"] == 4,            "cond2 false count"
    assert report["branches"][lbl1]["both_covered"] is True,    "cond1 both branches covered"
    assert report["branches"][lbl2]["both_covered"] is True,    "cond2 both branches covered"
    print("  PASS — all condition and branch counts correct")
    print("  PASS — both conditions have full branch coverage")
