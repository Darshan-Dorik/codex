"""
prompt_builder.py — Structured Prompt Builder

Converts an analysis payload (from analysis.json) into a compact,
structured text prompt suitable for an LLM.

Design rules:
  - No raw timelines — only summarised state at violation points
  - Top N failures only (configurable)
  - Violations grouped by property
  - Coverage gaps listed concisely
  - Total prompt kept well under token limits (see Step 8 for hard cap)
"""

import json


def build_prompt(payload, max_failures=3, max_violations_per_property=3,
                 task="general"):
    """
    Build a structured prompt from an analysis payload dict.

    Args:
        payload                     : dict — analysis payload (from analysis.json)
        max_failures                : int  — max failure entries to include
        max_violations_per_property : int  — max violation examples per property
        task : str — one of:
                "general"       — full context prompt
                "failures"      — focus on failures only
                "coverage"      — focus on coverage gaps only
                "violations"    — focus on property violations only
                "suggestions"   — focus on missing test scenarios

    Returns:
        str — the formatted prompt text
    """
    lines = []

    # --- Header ---
    lines.append("You are analyzing a PLC (Programmable Logic Controller) "
                 "validation report.")
    lines.append(f"Program: {payload.get('program', 'unknown')}")
    lines.append("")

    # --- Summary ---
    s = payload.get("summary", {})
    lines.append("=== SUMMARY ===")
    lines.append(f"Total scenarios run : {s.get('total_runs', 0)}")
    lines.append(f"Passed              : {s.get('passed', 0)}")
    lines.append(f"Failed              : {s.get('failed', 0)}")
    lines.append(f"Property violations : {s.get('violations', 0)}")
    lines.append(f"Coverage gaps found : {s.get('has_gaps', False)}")
    lines.append("")

    # --- Failures ---
    if task in ("general", "failures"):
        failures = payload.get("failures", [])
        if failures:
            shown = failures[:max_failures]
            lines.append(f"=== FAILURES (showing {len(shown)} of "
                         f"{len(failures)}) ===")
            for f in shown:
                lines.append(f"Scenario: {f['scenario']}  "
                             f"[{f['status'].upper()}]")
                for err in f.get("errors", []):
                    lines.append(f"  Assertion failed: {err}")
                for v in f.get("violations", [])[:max_violations_per_property]:
                    st = v.get("state", {})
                    lines.append(
                        f"  Violation at t={v['time']}ms: {v['property']}"
                    )
                    lines.append(
                        f"    inputs={st.get('inputs',{})}  "
                        f"outputs={st.get('outputs',{})}"
                    )
            lines.append("")
        else:
            lines.append("=== FAILURES ===")
            lines.append("None.")
            lines.append("")

    # --- Property violations summary ---
    if task in ("general", "violations"):
        viols = payload.get("violations", [])
        if viols:
            lines.append("=== PROPERTY VIOLATIONS ===")
            for v in viols:
                lines.append(f"Property : {v['property']}")
                lines.append(f"  Count    : {v['count']}")
                lines.append(f"  Scenarios: {v['scenarios']}")
            lines.append("")
        else:
            lines.append("=== PROPERTY VIOLATIONS ===")
            lines.append("None.")
            lines.append("")

    # --- Coverage gaps ---
    if task in ("general", "coverage", "suggestions"):
        gaps = payload.get("coverage_gaps", {})
        has_any_gap = any([
            gaps.get("conditions_never_true"),
            gaps.get("conditions_never_false"),
            gaps.get("branches_never_then"),
            gaps.get("branches_never_else")
        ])
        lines.append("=== COVERAGE GAPS ===")
        if has_any_gap:
            if gaps.get("conditions_never_true"):
                lines.append("Conditions never evaluated TRUE:")
                for c in gaps["conditions_never_true"]:
                    lines.append(f"  - {c}")
            if gaps.get("conditions_never_false"):
                lines.append("Conditions never evaluated FALSE:")
                for c in gaps["conditions_never_false"]:
                    lines.append(f"  - {c}")
            if gaps.get("branches_never_then"):
                lines.append("THEN branches never executed:")
                for c in gaps["branches_never_then"]:
                    lines.append(f"  - {c}")
            if gaps.get("branches_never_else"):
                lines.append("ELSE branches never executed:")
                for c in gaps["branches_never_else"]:
                    lines.append(f"  - {c}")
        else:
            lines.append("No coverage gaps detected.")
        if gaps.get("fully_covered"):
            lines.append("Fully covered conditions:")
            for c in gaps["fully_covered"]:
                lines.append(f"  ✓ {c}")
        lines.append("")

    # --- Task-specific question ---
    lines.append("=== QUESTION ===")
    questions = {
        "general":
            "Based on the above validation report, provide a brief analysis "
            "covering: (1) likely root causes of failures, "
            "(2) risks from coverage gaps, "
            "(3) safety concerns from violations.",
        "failures":
            "Explain the possible root causes of the failures listed above. "
            "Be specific about what PLC logic conditions could cause them.",
        "coverage":
            "Which conditions are untested and why is that risky for a "
            "PLC controlling industrial machinery?",
        "violations":
            "What unsafe machine states occurred based on the property "
            "violations above, and how should the PLC logic be fixed "
            "to prevent them?",
        "suggestions":
            "Suggest 3-5 new test scenarios that would cover the missing "
            "branches listed above. For each scenario, describe the input "
            "combination and what behavior it would test."
    }
    lines.append(questions.get(task, questions["general"]))

    return "\n".join(lines)


def load_and_build_prompt(json_path, **kwargs):
    """
    Load analysis.json from disk and build a prompt.

    Args:
        json_path : str — path to analysis JSON file
        **kwargs  : passed to build_prompt()

    Returns:
        str — the formatted prompt
    """
    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return build_prompt(payload, **kwargs)


if __name__ == "__main__":
    import os

    print("=" * 60)
    print("Phase 6 - Step 2: Structured Prompt Builder")
    print("=" * 60)

    # Use the shuttle analysis file generated in Phase 5
    json_path = "analysis_shuttle.json"

    if not os.path.exists(json_path):
        print(f"  {json_path} not found — run export_analysis.py first")
        exit(1)

    with open(json_path) as f:
        payload = json.load(f)

    # --- Test 1: general prompt ---
    print("\nTest 1 — task='general':")
    print("-" * 60)
    p1 = build_prompt(payload, task="general")
    print(p1)
    print("-" * 60)
    print(f"  Prompt length: {len(p1)} chars")

    # --- Test 2: violations-only prompt ---
    print("\nTest 2 — task='violations':")
    print("-" * 60)
    p2 = build_prompt(payload, task="violations")
    print(p2)
    print("-" * 60)

    # --- Test 3: suggestions prompt ---
    print("\nTest 3 — task='suggestions':")
    print("-" * 60)
    p3 = build_prompt(payload, task="suggestions")
    print(p3)
    print("-" * 60)

    # --- Test 4: max_failures cap ---
    print("\nTest 4 — max_failures=1 (cap test):")
    print("-" * 60)
    p4 = build_prompt(payload, task="failures", max_failures=1)
    print(p4)
    print("-" * 60)

    # --- Assertions ---
    print("\n--- Assertions ---")

    assert "SUMMARY"            in p1, "general prompt must have SUMMARY"
    assert "FAILURES"           in p1, "general prompt must have FAILURES"
    assert "PROPERTY VIOLATIONS" in p1, "general prompt must have VIOLATIONS"
    assert "COVERAGE GAPS"      in p1, "general prompt must have COVERAGE GAPS"
    assert "QUESTION"           in p1, "general prompt must have QUESTION"
    print("  PASS — general prompt has all 5 sections")

    assert "PROPERTY VIOLATIONS" in p2
    assert "FAILURES"           not in p2, "violations prompt must not have FAILURES"
    print("  PASS — violations prompt has correct sections only")

    assert "COVERAGE GAPS"      in p3
    assert "Suggest"            in p3, "suggestions prompt must ask for suggestions"
    print("  PASS — suggestions prompt has coverage gaps + suggestion question")

    assert len(p1) > 100,  "prompt must be non-trivial"
    assert len(p1) < 8000, "prompt must be within reasonable size"
    print(f"  PASS — prompt length {len(p1)} chars (within bounds)")
