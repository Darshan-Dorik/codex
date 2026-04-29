"""
tool/orchestrator.py — Workflow Orchestrator

Executes the full validation pipeline from a loaded config dict.

Pipeline stages:
  1. Load ST program
  2. Load calibration profile (optional)
  3. Build safety properties
  4. Generate scenarios
  5. Run simulation (batch execution)
  6. Aggregate results
  7. AI analysis (optional)

Returns a structured result dict consumed by the output manager.
"""

import sys
import os
import io

# Ensure project root is importable
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _subdir in ("", "src/core", "src/testing", "src/batch",
                "src/analysis", "src/ai"):
    _p = os.path.join(_ROOT, _subdir)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from st_loader import load_st_file
from st_parser import parse_st
from scenario_generator import generate_scenarios
from batch_executor import execute_scenarios
from aggregator import aggregate_results
from properties import make_property
from calibration import (DEFAULT_PROFILE, load_profile,
                         build_calibration_report, measure_twin,
                         calculate_errors, total_error_score)


def _build_properties(property_configs):
    """
    Build property dicts from config entries.

    Each config entry has:
      {"name": str, "check": str}   # check is a lambda expression string
    """
    props = []
    for pc in property_configs:
        try:
            fn = eval(pc["check"])   # safe: operator-supplied config only
            props.append(make_property(pc["name"], fn))
        except Exception as e:
            raise ValueError(
                f"Invalid property check for '{pc['name']}': {e}"
            )
    return props


def run_pipeline(config, verbose=True):
    """
    Execute the full validation pipeline.

    Args:
        config  : dict — validated config from load_config()
        verbose : bool — print progress to stdout

    Returns:
        {
          "status":       "success" | "error",
          "error":        str | None,
          "program":      str,
          "scenarios_run": int,
          "results":      [...],      # raw batch results
          "aggregation":  {...},      # from aggregate_results()
          "calibration":  {...} | None,
          "ai_report":    {...} | None
        }
    """
    def log(msg):
        if verbose:
            print(f"  {msg}")

    result = {
        "status":        "success",
        "error":         None,
        "program":       config["program"],
        "scenarios_run": 0,
        "results":       [],
        "aggregation":   {},
        "calibration":   None,
        "ai_report":     None
    }

    try:
        # -------------------------------------------------------
        # Stage 1: Load ST program
        # -------------------------------------------------------
        log(f"[1/6] Loading program: {config['program']}")
        st_code = load_st_file(config["program"])
        logic   = parse_st(st_code)
        log(f"      Parsed {len(logic)} logic block(s)")

        # -------------------------------------------------------
        # Stage 2: Load calibration profile
        # -------------------------------------------------------
        cal_path = config.get("calibration")
        if cal_path:
            log(f"[2/6] Loading calibration: {cal_path}")
            profile = load_profile(cal_path)
        else:
            log("[2/6] No calibration profile — using defaults")
            profile = DEFAULT_PROFILE

        # -------------------------------------------------------
        # Stage 3: Build safety properties
        # -------------------------------------------------------
        prop_configs = config.get("properties", [])
        log(f"[3/6] Building {len(prop_configs)} safety propert(y/ies)")
        properties = _build_properties(prop_configs)

        # -------------------------------------------------------
        # Stage 4: Generate scenarios
        # -------------------------------------------------------
        sc_cfg = config["scenarios"]
        log(f"[4/6] Generating scenarios: inputs={sc_cfg['inputs']} "
            f"max={sc_cfg['max_scenarios']}")
        gen = generate_scenarios(
            inputs=sc_cfg["inputs"],
            timing=sc_cfg["timing"],
            max_scenarios=sc_cfg["max_scenarios"],
            base_name="scenario"
        )
        scenarios = gen["scenarios"]
        log(f"      Generated {gen['generated']} scenario(s) "
            f"(total possible: {gen['total_possible']}, "
            f"capped: {gen['capped']})")

        # -------------------------------------------------------
        # Stage 5: Run simulation
        # -------------------------------------------------------
        log(f"[5/6] Running simulation ({len(scenarios)} scenarios, "
            f"step={sc_cfg['step_ms']}ms)")

        # Suppress per-tick output
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        batch_results = execute_scenarios(
            scenarios=scenarios,
            logic=logic,
            max_time_ms=max(sc_cfg["timing"]) + sc_cfg["step_ms"] * 5,
            step_ms=sc_cfg["step_ms"],
            properties=properties
        )
        sys.stdout = old_stdout

        result["scenarios_run"] = len(batch_results)
        result["results"]       = batch_results
        log(f"      Completed {len(batch_results)} scenario(s)")

        # -------------------------------------------------------
        # Stage 6: Aggregate results
        # -------------------------------------------------------
        log("[6/6] Aggregating results")
        agg = aggregate_results(batch_results)
        result["aggregation"] = agg

        # Calibration report (if real_world targets provided)
        real_world = config.get("real_world", {})
        if real_world:
            measured = measure_twin(profile, sc_cfg["step_ms"])
            errors   = calculate_errors(measured, real_world)
            score    = total_error_score(errors)
            result["calibration"] = {
                "profile_name": profile.get("name", "unknown"),
                "score":        score,
                "errors":       {
                    k: {
                        "expected":  e["expected"],
                        "measured":  e["measured"],
                        "error_pct": e["relative_error_pct"]
                    }
                    for k, e in errors.items()
                }
            }
            log(f"      Calibration score: {score}%")

        # -------------------------------------------------------
        # Stage 7: AI analysis (optional)
        # -------------------------------------------------------
        if config.get("ai_analysis"):
            log("[7/7] Running AI analysis...")
            try:
                from analysis_payload import build_analysis_payload
                from ai_report import build_ai_report

                payload    = build_analysis_payload(
                    config["program"], batch_results)
                ai_report  = build_ai_report(payload)
                result["ai_report"] = ai_report
                log("      AI analysis complete")
            except Exception as e:
                log(f"      AI analysis skipped: {e}")
        else:
            log("[7/7] AI analysis disabled")

    except Exception as e:
        sys.stdout = sys.__stdout__   # safety restore
        result["status"] = "error"
        result["error"]  = str(e)

    return result


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("Phase 10 - Step 3: Workflow Orchestrator")
    print("=" * 60)

    # Load the test config created in Step 1
    config_path = "outputs/test_config.json"
    if not os.path.exists(config_path):
        print(f"  {config_path} not found — run Step 1 first")
        sys.exit(1)

    sys.path.insert(0, os.path.join(_ROOT, "tool"))
    from config_loader import load_config

    config = load_config(config_path)

    print(f"\nRunning pipeline for: {config['program']}")
    print("-" * 50)

    result = run_pipeline(config, verbose=True)

    print()
    print("=" * 60)
    print("  PIPELINE RESULT")
    print("=" * 60)
    print(f"  status        : {result['status']}")
    if result["error"]:
        print(f"  error         : {result['error']}")
    print(f"  program       : {result['program']}")
    print(f"  scenarios_run : {result['scenarios_run']}")
    agg = result["aggregation"]
    print(f"  passed        : {agg.get('passed', 0)}")
    print(f"  failed        : {agg.get('failed', 0)}")
    print(f"  violations    : {agg.get('violations', 0)}")
    if result["calibration"]:
        print(f"  cal score     : {result['calibration']['score']}%")

    # --- Assertions ---
    print("\n--- Assertions ---")

    assert result["status"] == "success",       "pipeline must succeed"
    print("  PASS — pipeline completed successfully")

    assert result["scenarios_run"] > 0,         "must run at least 1 scenario"
    print(f"  PASS — {result['scenarios_run']} scenarios executed")

    assert "passed" in result["aggregation"],   "aggregation must have passed"
    assert "failed" in result["aggregation"],   "aggregation must have failed"
    print("  PASS — aggregation has passed/failed counts")

    assert result["ai_report"] is None,         "AI disabled → no ai_report"
    print("  PASS — AI analysis correctly skipped")

    # Error path: bad program path
    bad_config = dict(config)
    bad_config["program"] = "programs/nonexistent.st"
    bad_result = run_pipeline(bad_config, verbose=False)
    assert bad_result["status"] == "error",     "bad program must return error"
    assert bad_result["error"]  is not None
    print(f"  PASS — bad program path returns error: {bad_result['error']}")
