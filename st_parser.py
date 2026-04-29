import re
import json


# ---------------------------------------------------------------------------
# Condition expression parser
# Supports: variable names, NOT, AND, OR  (precedence: NOT > AND > OR)
# Produces a nested dict expression tree.
#
# Grammar (simplified):
#   expr    := or_expr
#   or_expr := and_expr  ( 'OR'  and_expr )*
#   and_expr:= not_expr  ( 'AND' not_expr )*
#   not_expr:= 'NOT' not_expr | atom
#   atom    := '(' expr ')' | IDENTIFIER
# ---------------------------------------------------------------------------

def _tokenize(condition_str):
    """Split condition string into tokens: keywords, identifiers, parentheses."""
    token_pattern = re.compile(
        r'\bNOT\b|\bAND\b|\bOR\b|[()]|[A-Za-z_][A-Za-z0-9_]*',
        re.IGNORECASE
    )
    return [t.upper() for t in token_pattern.findall(condition_str)]


class _Parser:
    """Recursive-descent parser for boolean condition expressions."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self, expected=None):
        tok = self.tokens[self.pos]
        if expected and tok != expected:
            raise SyntaxError(f"Expected '{expected}', got '{tok}'")
        self.pos += 1
        return tok

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.peek() == "OR":
            self.consume("OR")
            right = self.parse_and()
            left = {"op": "OR", "left": left, "right": right}
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek() == "AND":
            self.consume("AND")
            right = self.parse_not()
            left = {"op": "AND", "left": left, "right": right}
        return left

    def parse_not(self):
        if self.peek() == "NOT":
            self.consume("NOT")
            operand = self.parse_not()   # right-associative
            return {"op": "NOT", "operand": operand}
        return self.parse_atom()

    def parse_atom(self):
        tok = self.peek()
        if tok == "(":
            self.consume("(")
            node = self.parse_expr()
            self.consume(")")
            return node
        if tok and tok not in ("AND", "OR", "NOT", "(", ")"):
            self.consume()
            return {"op": "VAR", "name": tok}
        raise SyntaxError(f"Unexpected token '{tok}' at position {self.pos}")


def parse_condition(condition_str):
    """
    Parse a boolean condition string into a nested expression tree.

    Supported operators: AND, OR, NOT  (case-insensitive)
    Supported atoms: variable names (e.g. X0, X1, SENSOR_A)

    Returns a dict expression node, e.g.:
      "X0 AND NOT X1"  ->
      {
        "op": "AND",
        "left":  {"op": "VAR", "name": "X0"},
        "right": {"op": "NOT", "operand": {"op": "VAR", "name": "X1"}}
      }
    """
    tokens = _tokenize(condition_str.strip())
    if not tokens:
        raise SyntaxError("Empty condition string")
    parser = _Parser(tokens)
    tree = parser.parse_expr()
    if parser.pos != len(parser.tokens):
        raise SyntaxError(
            f"Unexpected token '{parser.peek()}' after valid expression"
        )
    return tree


# ---------------------------------------------------------------------------
# Original simple parser — preserved for backward compatibility
# Now delegates condition parsing to parse_condition()
# ---------------------------------------------------------------------------

def parse_st(st_code):
    """
    Parses minimal Structured Text:
    IF <condition> THEN <var> := TRUE/FALSE; END_IF;

    Condition may now include AND, OR, NOT and parentheses.
    Produces internal 'assign' rules with a structured 'condition' tree
    instead of a plain string variable name.
    """
    logic = []

    pattern = re.compile(
        r"IF\s+(.+?)\s+THEN\s+(.+?)\s*:=\s*(TRUE|FALSE)\s*;\s*END_IF;",
        re.IGNORECASE | re.DOTALL
    )

    matches = pattern.findall(st_code)
    for match in matches:
        cond_str   = match[0].strip()
        target_var = match[1].strip()
        val        = match[2].strip().upper()

        if val == "TRUE":
            logic.append({
                "type":      "assign",
                "condition": parse_condition(cond_str),
                "set":       target_var
            })

    return logic


if __name__ == "__main__":
    print("Phase 4 - Step 1: Extended ST Parser — Boolean Expressions\n")

    # --- Test 1: simple variable (backward-compatible) ---
    t1 = "X0"
    print(f"Test 1 — Simple variable: '{t1}'")
    print(json.dumps(parse_condition(t1), indent=2))

    # --- Test 2: NOT ---
    t2 = "NOT X1"
    print(f"\nTest 2 — NOT: '{t2}'")
    print(json.dumps(parse_condition(t2), indent=2))

    # --- Test 3: AND ---
    t3 = "X0 AND X1"
    print(f"\nTest 3 — AND: '{t3}'")
    print(json.dumps(parse_condition(t3), indent=2))

    # --- Test 4: AND NOT (the key new case) ---
    t4 = "X0 AND NOT X1"
    print(f"\nTest 4 — AND NOT: '{t4}'")
    print(json.dumps(parse_condition(t4), indent=2))

    # --- Test 5: OR ---
    t5 = "X0 OR X2"
    print(f"\nTest 5 — OR: '{t5}'")
    print(json.dumps(parse_condition(t5), indent=2))

    # --- Test 6: complex expression with parentheses ---
    t6 = "(X0 OR X1) AND NOT X2"
    print(f"\nTest 6 — Complex: '{t6}'")
    print(json.dumps(parse_condition(t6), indent=2))

    # --- Test 7: full parse_st with boolean condition ---
    print("\nTest 7 — parse_st with boolean condition:")
    st_code = """
    IF X0 AND NOT X1 THEN
        Y0 := TRUE;
    END_IF;
    """
    print(f"  Input ST:\n{st_code.strip()}")
    result = parse_st(st_code)
    print("\n  Parsed logic:")
    print(json.dumps(result, indent=2))
