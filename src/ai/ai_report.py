"""
ai_report.py — Consolidated AI Report

Combines outputs from all AI analysis modules into a single
structured report dict.

Output schema:
{
  "program":           str,
  "failure_analysis":  str,
  "coverage_analysis": str,
  "suggested_tests":   str,
  "safety_insights":   str,
  "prompts": {
    "failures":   str,
    "coverage":   str,
    "suggestions": str,
    "safety":     str
  },
  "meta": {
    "failures_included":  int,
    "has_gaps":           bool,
    "has_violations":     bool,
    "any_skipped":        bool
  }
}
"""

import json
import os
from failure_explainer import explain_failures
from coverage_analyzer import analyze_coverage
from scenario_suggester import suggest_scenarios
from safety_analyzer import analyze_safety


def build_ai_report(payload, max_failures=3, model=None):
    """
    Run all AI analysis modules and combine into a single report.

    Args:
        payload      : dict — analysis payload
        max_failures : int  — max failures to include in failure prompt
        model        : str  — Ollama model override

    Returns:
        consolidated AI report dict
    """
    kwargs = {"model": model} if model else {}

    fail_result = explain_failures(payload, max_failures=max_failures, **kwargs)
    cov_result  = analyze_coverage(payload, **kwargs)
    sug_result  = suggest_scenarios(payload, **kwargs)
    safe_result = analyze_safety(payload, **kwargs)

    any_skipped = any([
        fail_result["skipped"],
        cov_result["skipped"],
        sug_result["skipped"],
        safe_result["skipped"]
    ])

    return {
        "program":           payload.get("program", "unknown"),
        "failure_analysis":  fail_result["explanation"],
        "coverage_analysis": cov_result["analysis"],
        "suggested_tests":   sug_result["suggestions"],
        "safety_insights":   safe_result["insights"],
        "prompts": {
            "failures":    fail_result["prompt"],
            "coverage":    cov_result["prompt"],
            "suggestions": sug_result["prompt"],
            "safety":      safe_result["prompt"]
        },
        "meta": {
            "failures_included": fail_result.get("failures_included", 0),
            "has_gaps":          cov_result["has_gaps"],
            "has_violations":    safe_result["has_violations"],
            "any_skipped":       any_skipped
        }
    }


def print_ai_report(report):
    """Print the consolidated AI report in a readable format."""
    print("=" * 60)
    print("  CONSOLIDATED AI REPORT")
    print("=" * 60)
    print(f"  Program : {report['program']}")
    m = report["meta"]
    print(f"  Meta    : failures_included={m['failures_included']}  "
          f"has_gaps={m['has_gaps']}  "
          f"has_violations={m['has_violations']}  "
          f"any_skipped={m['any_skipped']}")

    sections = [
        ("FAILURE ANALYSIS",  "failure_analysis"),
        ("COVERAGE ANALYSIS", "coverage_analysis"),
        ("SUGGESTED TESTS",   "suggested_tests"),
        ("SAFETY INSIGHTS",   "safety_insights"),
    ]
    for title, key in sections:
        print(f"\n  --- {title} ---")
        text = report.get(key, "")
        print(f"  {text}" if text else "  (none)")
    print("=" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 6 - Step 7: Consolidated AI Report")
    print("=" * 60)

    # Use shuttle analysis (has violations) for a rich report
    json_path = "analysis_shuttle.json"
    if not os.path.exists(json_path):
        print(f"  {json_path} not found — run export_analysis.py first")
        exit(1)

    with open(json_path) as f:
        payload = json.load(f)

    print(f"\nBuilding consolidated report for: {json_path}")
    report = build_ai_report(payload, max_failures=3)

    print_ai_report(report)

    # Assertions
    print("\n--- Assertions ---")
    for key in ("program", "failure_analysis", "coverage_analysis",
                "suggested_tests", "safety_insights", "prompts", "meta"):
        assert key in report, f"missing key: {key}"
    print("  PASS — all required keys present")

    for key in ("failures", "coverage", "suggestions", "safety"):
        assert key in report["prompts"], f"missing prompt key: {key}"
    print("  PASS — all prompt keys present")

    for key in ("failures_included", "has_gaps", "has_violations", "any_skipped"):
        assert key in report["meta"], f"missing meta key: {key}"
    print("  PASS — all meta keys present")

    assert isinstance(report["failure_analysis"], str)
    assert isinstance(report["safety_insights"], str)
    print("  PASS — all analysis fields are strings")
