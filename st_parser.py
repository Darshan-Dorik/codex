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
# Supports: IF/THEN/END_IF  and  IF/THEN/ELSE/END_IF
# ---------------------------------------------------------------------------

def _parse_assignment(stmt):
    """
    Parse a single assignment statement: '<var> := TRUE|FALSE ;'
    Returns a dict or None if the statement doesn't match.
    """
    stmt = stmt.strip()
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*:=\s*(TRUE|FALSE)\s*;?$',
                 stmt, re.IGNORECASE)
    if not m:
        return None
    return {
        "type":   "set",
        "target": m.group(1).upper(),
        "value":  m.group(2).upper() == "TRUE"
    }


def _parse_body(body_str):
    """
    Parse a THEN or ELSE body string into a list of assignment dicts.
    Each statement is separated by ';'.
    """
    statements = []
    # Split on semicolons, strip whitespace, skip empty
    for stmt in body_str.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        parsed = _parse_assignment(stmt + ";")
        if parsed:
            statements.append(parsed)
    return statements


def parse_st(st_code):
    """
    Parses Structured Text blocks of the form:

      IF <condition> THEN
          <assignments>
      END_IF;

      IF <condition> THEN
          <assignments>
      ELSE
          <assignments>
      END_IF;

    Condition may include AND, OR, NOT and parentheses.

    Returns a list of rule dicts:
      - No ELSE:  {"type": "if_else", "condition": <tree>,
                   "then_body": [...], "else_body": []}
      - With ELSE: {"type": "if_else", "condition": <tree>,
                    "then_body": [...], "else_body": [...]}
    """
    logic = []

    # Match each IF...END_IF block (non-greedy, DOTALL)
    block_pattern = re.compile(
        r'IF\s+(.+?)\s+THEN\s+(.*?)\s*END_IF\s*;',
        re.IGNORECASE | re.DOTALL
    )

    for m in block_pattern.finditer(st_code):
        cond_str  = m.group(1).strip()
        body_str  = m.group(2).strip()

        # Split body on ELSE keyword (case-insensitive, whole word)
        else_split = re.split(r'\bELSE\b', body_str, maxsplit=1, flags=re.IGNORECASE)

        then_str = else_split[0].strip()
        else_str = else_split[1].strip() if len(else_split) == 2 else ""

        logic.append({
            "type":      "if_else",
            "condition": parse_condition(cond_str),
            "then_body": _parse_body(then_str),
            "else_body": _parse_body(else_str)
        })

    return logic


if __name__ == "__main__":
    print("Phase 4 - Step 3: Multiple Statements per Block\n")

    # --- Test 1: Two assignments in THEN, two in ELSE ---
    st_multi = """
    IF X0 THEN
        Y0 := TRUE;
        Y1 := TRUE;
    ELSE
        Y0 := FALSE;
        Y1 := FALSE;
    END_IF;
    """
    print("Test 1 — Two assignments in THEN and ELSE:")
    print(f"  Input:\n{st_multi.strip()}\n")
    result = parse_st(st_multi)
    print("  Parsed:")
    print(json.dumps(result, indent=2))

    # --- Test 2: Three assignments in THEN, one in ELSE ---
    st_mixed = """
    IF X0 AND NOT X1 THEN
        Y0 := TRUE;
        Y1 := TRUE;
        Y2 := FALSE;
    ELSE
        Y0 := FALSE;
    END_IF;
    """
    print("\nTest 2 — Three assignments in THEN, one in ELSE:")
    print(f"  Input:\n{st_mixed.strip()}\n")
    result2 = parse_st(st_mixed)
    print("  Parsed:")
    print(json.dumps(result2, indent=2))

    # --- Test 3: Multiple statements, no ELSE ---
    st_no_else = """
    IF X0 OR X2 THEN
        Y0 := TRUE;
        Y1 := FALSE;
    END_IF;
    """
    print("\nTest 3 — Two assignments, no ELSE:")
    print(f"  Input:\n{st_no_else.strip()}\n")
    result3 = parse_st(st_no_else)
    print("  Parsed:")
    print(json.dumps(result3, indent=2))

    # --- Structural assertions ---
    print("\n--- Structural Verification ---")

    # Test 1 checks
    r1 = result[0]
    assert r1["type"] == "if_else",          "type must be if_else"
    assert len(r1["then_body"]) == 2,        "then_body must have 2 statements"
    assert len(r1["else_body"]) == 2,        "else_body must have 2 statements"
    assert r1["then_body"][0]["target"] == "Y0" and r1["then_body"][0]["value"] is True
    assert r1["then_body"][1]["target"] == "Y1" and r1["then_body"][1]["value"] is True
    assert r1["else_body"][0]["target"] == "Y0" and r1["else_body"][0]["value"] is False
    assert r1["else_body"][1]["target"] == "Y1" and r1["else_body"][1]["value"] is False
    print("  Test 1: PASS — 2 statements in THEN and ELSE verified")

    # Test 2 checks
    r2 = result2[0]
    assert len(r2["then_body"]) == 3,        "then_body must have 3 statements"
    assert len(r2["else_body"]) == 1,        "else_body must have 1 statement"
    assert r2["then_body"][2]["target"] == "Y2" and r2["then_body"][2]["value"] is False
    print("  Test 2: PASS — 3 statements in THEN, 1 in ELSE verified")

    # Test 3 checks
    r3 = result3[0]
    assert len(r3["then_body"]) == 2,        "then_body must have 2 statements"
    assert len(r3["else_body"]) == 0,        "else_body must be empty"
    print("  Test 3: PASS — 2 statements in THEN, empty ELSE verified")

    print("\n  All structural assertions passed.")
