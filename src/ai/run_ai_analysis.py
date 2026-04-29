"""
run_ai_analysis.py — CLI Command for AI Analysis

Entry point: run_ai_analysis(analysis_json_path)

Runs the full AI analysis pipeline on a saved analysis.json file and:
  1. Prints insights to console
  2. Saves ai_report.json
  3. Saves prompt_snapshot.json

Usage:
  python run_ai_analysis.py analysis_shuttle.json
  python run_ai_analysis.py analysis_motor.json --model mistral:latest
"""

import json
import os
import sys
import argparse

from ai_report import build_ai_report, print_ai_report
from prompt_snapshot import save_prompt_snapshot
from prompt_limiter import build_limited_prompt
from ollama_client import is_ollama_available


def run_ai_analysis(analysis_path, model=None, max_tokens=2048,
                    output_dir=None):
    """
    Run the full AI analysis pipeline on an analysis.json file.

    Args:
        analysis_path : str  — path to analysis.json
        model         : str  — Ollama model override
        max_tokens    : int  — prompt token budget
        output_dir    : str  — directory for output files (default: same as input)

    Returns:
        dict — the AI report
    """
    if not os.path.exists(analysis_path):
        raise FileNotFoundError(f"Analysis file not found: {analysis_path}")

    with open(analysis_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    # Determine output directory
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(analysis_path))

    base_name = os.path.splitext(os.path.basename(analysis_path))[0]
    report_path   = os.path.join(output_dir, f"ai_report_{base_name}.json")
    snapshot_path = os.path.join(output_dir, f"prompt_snapshot_{base_name}.json")

    print(f"\n{'=' * 60}")
    print(f"  AI ANALYSIS: {analysis_path}")
    print(f"{'=' * 60}")

    # Check Ollama availability
    available, status_msg = is_ollama_available()
    print(f"\n  Ollama: {status_msg}")

    if not available:
        print("\n  WARNING: Ollama not available. "
              "Saving prompt snapshot only (no LLM responses).")
        from prompt_builder import build_prompt
        report = {
            "program": payload.get("program", "unknown"),
            "failure_analysis":  "[SKIPPED] Ollama not available",
            "coverage_analysis": "[SKIPPED] Ollama not available",
            "suggested_tests":   "[SKIPPED] Ollama not available",
            "safety_insights":   "[SKIPPED] Ollama not available",
            "prompts": {
                "failures":    build_prompt(payload, task="failures"),
                "coverage":    build_prompt(payload, task="coverage"),
                "suggestions": build_prompt(payload, task="suggestions"),
                "safety":      build_prompt(payload, task="violations")
            },
            "meta": {
                "failures_included": 0,
                "has_gaps":          False,
                "has_violations":    False,
                "any_skipped":       True
            }
        }
    else:
        # Apply prompt size control
        limited = build_limited_prompt(payload, task="general",
                                       max_tokens=max_tokens)
        print(f"\n  Prompt size: ~{limited['estimated_tokens']} tokens "
              f"(limit: {max_tokens})  "
              f"truncated: {limited['truncated']}")

        print("\n  Running AI analysis modules...")
        report = build_ai_report(payload, max_failures=3, model=model)

    # Print report to console
    print_ai_report(report)

    # Save AI report
    # Remove non-serialisable callables if any slipped through
    report_to_save = {k: v for k, v in report.items()}
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_to_save, f, indent=2)
    print(f"\n  AI report saved  : {report_path}")

    # Save prompt snapshot
    save_prompt_snapshot(report, snapshot_path)
    print(f"  Prompt snapshot  : {snapshot_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run AI analysis on a PLC validation analysis.json file"
    )
    parser.add_argument(
        "analysis_file",
        nargs="?",
        default="analysis_shuttle.json",
        help="Path to analysis.json (default: analysis_shuttle.json)"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Ollama model name (default: mistral:latest)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help="Prompt token budget (default: 2048)"
    )
    args = parser.parse_args()

    report = run_ai_analysis(
        args.analysis_file,
        model=args.model,
        max_tokens=args.max_tokens
    )

    # Verify output files exist
    print("\n--- Output File Verification ---")
    base = os.path.splitext(os.path.basename(args.analysis_file))[0]
    for fname in (f"ai_report_{base}.json", f"prompt_snapshot_{base}.json"):
        exists = os.path.exists(fname)
        print(f"  {'PASS' if exists else 'FAIL'} — {fname}")
        if exists:
            with open(fname) as f:
                data = json.load(f)
            print(f"         keys: {list(data.keys())}")
