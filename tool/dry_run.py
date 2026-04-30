"""
tool/dry_run.py — Dry Run Mode

Performs pre-flight validation of a config without running the simulation.

Checks:
  1. Config structure (already done by load_config)
  2. ST program file exists and parses without errors
  3. Calibration profile file exists and is valid (if specified)
  4. Property lambda expressions compile and are callable
  5. Output directory is writable
  6. Reports what the run WOULD do (scenario count, etc.)

Returns a structured result — no simulation is executed.
"""

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _subdir in ("", "src/core", "src/testing", "src/batch",
                "src/analysis", "src/ai", "tool"):
    _p = os.path.join(_ROOT, _subdir)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def run_dry_run(config):
    """
    Perform pre-flight checks on a validated config.

    Args:
        config : dict — from load_config()

    Returns:
        {
          "passed":   bool,
          "checks":   [{"name": str, "status": "OK"|"FAIL"|"WARN",
                        "detail": str}],
          "preview":  {...}   # what the run would do
        }
    """
    checks  = []
    passed  = True

    def ok(name, detail=""):
        checks.append({"name": name, "status": "OK", "detail": detail})

    def fail(name, detail):
        nonlocal passed
        passed = False
        checks.append({"name": name, "status": "FAIL", "detail": detail})

    def warn(name, detail):
        checks.append({"name": name, "status": "WARN", "detail": detail})

    # -------------------------------------------------------
    # Check 1: ST program file exists
    # -------------------------------------------------------
    program = config["program"]
    if not os.path.exists(program):
        fail("ST program file", f"Not found: {program}")
    else:
        ok("ST program file", program)

        # Check 2: ST program parses
        try:
            from st_loader import load_st_file
            from st_parser import parse_st
            st_code = load_st_file(program)
            logic   = parse_st(st_code)
            if logic:
                ok("ST program parse", f"{len(logic)} logic block(s) parsed")
            else:
                warn("ST program parse",
                     "Parsed 0 logic blocks — program may be empty")
        except Exception as e:
            fail("ST program parse", str(e))

    # -------------------------------------------------------
    # Check 3: Calibration profile (optional)
    # -------------------------------------------------------
    cal_path = config.get("calibration")
    if cal_path:
        if not os.path.exists(cal_path):
            fail("Calibration profile", f"Not found: {cal_path}")
        else:
            try:
                from calibration import load_profile
                load_profile(cal_path)
                ok("Calibration profile", cal_path)
            except Exception as e:
                fail("Calibration profile", str(e))
    else:
        ok("Calibration profile", "(none — using defaults)")

    # -------------------------------------------------------
    # Check 4: Property lambda expressions
    # -------------------------------------------------------
    prop_configs = config.get("properties", [])
    if not prop_configs:
        ok("Safety properties", "(none defined)")
    else:
        for i, pc in enumerate(prop_configs):
            name  = pc.get("name", f"property_{i}")
            check = pc.get("check", "")
            try:
                fn = eval(check)
                if not callable(fn):
                    fail(f"Property '{name}'",
                         "check expression is not callable")
                else:
                    # Test with a dummy state
                    fn({"time": 0, "inputs": {}, "outputs": {}})
                    ok(f"Property '{name}'", "lambda compiles and runs")
            except Exception as e:
                fail(f"Property '{name}'", f"lambda error: {e}")

    # -------------------------------------------------------
    # Check 5: Output directory writable
    # -------------------------------------------------------
    out_dir = config["output_dir"]
    try:
        os.makedirs(out_dir, exist_ok=True)
        test_file = os.path.join(out_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        ok("Output directory", f"Writable: {out_dir}")
    except Exception as e:
        fail("Output directory", f"Not writable: {e}")

    # -------------------------------------------------------
    # Preview: what the run would do
    # -------------------------------------------------------
    sc_cfg = config["scenarios"]
    try:
        from scenario_generator import generate_scenarios
        gen = generate_scenarios(
            inputs=sc_cfg["inputs"],
            timing=sc_cfg["timing"],
            max_scenarios=sc_cfg["max_scenarios"],
            base_name="preview"
        )
        preview = {
            "scenarios_would_run": gen["generated"],
            "total_possible":      gen["total_possible"],
            "capped":              gen["capped"],
            "inputs":              sc_cfg["inputs"],
            "timing_ms":           sc_cfg["timing"],
            "step_ms":             sc_cfg["step_ms"],
            "ai_analysis":         config.get("ai_analysis", False),
            "properties_count":    len(prop_configs)
        }
    except Exception as e:
        preview = {"error": str(e)}

    return {
        "passed":  passed,
        "checks":  checks,
        "preview": preview
    }


def print_dry_run_result(result):
    """Print dry run results in a readable format."""
    print("=" * 60)
    print("  DRY RUN — PRE-FLIGHT CHECK")
    print("=" * 60)

    for c in result["checks"]:
        icon = "✓" if c["status"] == "OK" else \
               "⚠" if c["status"] == "WARN" else "✗"
        detail = f"  {c['detail']}" if c["detail"] else ""
        print(f"  [{c['status']:4}] {icon}  {c['name']}{detail}")

    print()
    p = result["preview"]
    if "error" not in p:
        print("  What this run would do:")
        print(f"    Scenarios  : {p['scenarios_would_run']} "
              f"(of {p['total_possible']} possible"
              f"{', capped' if p['capped'] else ''})")
        print(f"    Inputs     : {p['inputs']}")
        print(f"    Timing     : {p['timing_ms']}ms")
        print(f"    Step size  : {p['step_ms']}ms")
        print(f"    Properties : {p['properties_count']}")
        print(f"    AI analysis: {p['ai_analysis']}")

    print()
    status = "READY TO RUN" if result["passed"] else "FIX ERRORS BEFORE RUNNING"
    icon   = "✓" if result["passed"] else "✗"
    print(f"  {icon}  {status}")
    print("=" * 60)


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("Phase 10 - Step 9: Dry Run Mode")
    print("=" * 60)

    from config_loader import load_config

    # -------------------------------------------------------
    # Test 1: valid config — all checks pass
    # -------------------------------------------------------
    print("\nTest 1 — Valid config (all checks should pass):")
    config1 = load_config("outputs/test_config.json")
    result1 = run_dry_run(config1)
    print_dry_run_result(result1)

    # -------------------------------------------------------
    # Test 2: bad program path
    # -------------------------------------------------------
    print("\nTest 2 — Bad program path:")
    config2 = dict(config1)
    config2["program"] = "programs/nonexistent.st"
    result2 = run_dry_run(config2)
    print_dry_run_result(result2)

    # -------------------------------------------------------
    # Test 3: bad property lambda
    # -------------------------------------------------------
    print("\nTest 3 — Bad property lambda:")
    config3 = json.loads(json.dumps(config1))
    config3["properties"] = [
        {"name": "bad prop", "check": "lambda s: s['outputs']['UNDEFINED_KEY']"}
    ]
    result3 = run_dry_run(config3)
    print_dry_run_result(result3)

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    assert result1["passed"] is True,           "valid config must pass"
    ok_statuses = [c["status"] for c in result1["checks"]]
    assert all(s in ("OK", "WARN") for s in ok_statuses), \
        "all checks must be OK or WARN"
    print("  PASS — valid config: all checks OK/WARN")

    assert result2["passed"] is False,          "bad program must fail"
    fail_names = [c["name"] for c in result2["checks"] if c["status"] == "FAIL"]
    assert "ST program file" in fail_names,     "ST program check must fail"
    print(f"  PASS — bad program: FAIL on '{fail_names}'")

    assert result3["passed"] is False,          "bad lambda must fail"
    fail3 = [c for c in result3["checks"] if c["status"] == "FAIL"]
    assert any("bad prop" in c["name"] for c in fail3)
    print("  PASS — bad lambda: property check fails")

    # Preview is populated for valid config
    assert "scenarios_would_run" in result1["preview"]
    assert result1["preview"]["scenarios_would_run"] > 0
    print(f"  PASS — preview: {result1['preview']['scenarios_would_run']} "
          f"scenarios would run")
