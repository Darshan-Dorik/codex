# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **PLC validation harness and digital twin** for a circular loom (6-shuttle textile machine). It parses IEC 61131-3 Structured Text programs, executes them against a simulated PLC scan cycle wired to a physics-ish machine twin, sweeps generated input scenarios, checks safety properties, tracks condition/branch coverage, and optionally asks a *local* LLM (Ollama) to explain the failures.

Three loosely coupled parts live in one repo:

1. **`src/` + `calibration.py` + `loom_twin.py`** — the simulation/validation engine (pure Python stdlib, no third-party deps).
2. **`tool/`** — `loom-validate`, the config-driven CLI that wires the engine into one pipeline.
3. **`ui/`** — a React + react-three-fiber 3D dashboard fed by `ui/api_server.py` (a stdlib HTTP server running the twin in a thread).

`.kiro/specs/local-plc-ai-assistant/requirements.md` holds the original EARS-style requirements. `Machine data platform phased brief.md` describes a *different, future* product (multi-vendor OT data acquisition for extrusion plants) — it is a planning document, not a spec for the code in `src/`.

## Commands

```bash
# Primary CLI — everything runs through here
python3 tool/loom_validate.py --list-presets
python3 tool/loom_validate.py --preset quick_check --dry-run   # pre-flight only, no simulation
python3 tool/loom_validate.py --preset motor_start_basic       # full pipeline
python3 tool/loom_validate.py my_config.json
python3 tool/loom_validate.py --template > my_config.json      # starter config

# End-to-end acceptance test (presets, dry run, full runs, error paths, run log)
python3 tool/final_validation.py

# UI: backend on :5174, Vite dev server separately
python3 ui/api_server.py
cd ui && npm install && npm run dev     # also: npm run build, npm run lint
```

There is **no requirements.txt, no venv, and no pytest** — the Python side is stdlib-only by design. AI features additionally need `ollama serve` on `localhost:11434` with `mistral:latest`; every AI path degrades gracefully when Ollama is absent.

## Testing convention

Every module carries its own test suite in an `if __name__ == "__main__":` block that prints a labelled report and ends in bare `assert` statements. **Running a module *is* running its tests.** There is no test runner; add new tests to the module's `__main__` block in the same style.

Because modules import each other **flat** (`from st_parser import parse_st`, not `from src.core.st_parser import ...`) and there are no `__init__.py` files, most `src/` modules cannot be run directly. Set the path first:

```bash
export PYTHONPATH=.:src/core:src/testing:src/batch:src/analysis:src/ai:src/bridge
python3 src/testing/test_harness.py     # single module's self-test
python3 src/bridge/trace_diff.py
```

`src/core/plc.py`, `src/core/loom.py`, and `tool/*.py` set up `sys.path` themselves and run bare. `tool/orchestrator.py` is the canonical example of the path-injection preamble to copy when adding a new entry point.

### Symbols are program-scoped

`X1` is the **fault sensor** in `programs/motor_start.st` and the **position sensor** in `programs/shuttle_control.st`. A symbol has no meaning without knowing which ST program produced the trace, so `io_map.py` ships one map per program (`make_motor_start_io_map`, `make_shuttle_io_map`, selected via `io_map_for_program`). `make_loom_io_map` is the legacy unscoped map — it matches neither program exactly and mislabels `X1` on shuttle traces; it is retained only because existing call sites default to it.

The twin models a position sensor and a jam condition and has **no fault sensor at all**, so anything captured from `loom_twin` / `ui/api_server.py` is `shuttle_control`-scoped.

**`src/testing/system.py` is stale** — it calls `plc.scan(dt=...)` and `loom.update(dt=...)` against the old signatures (both now take `current_time_ms`). Don't treat it as a reference.

## Architecture

### Execution model

`PLC.scan(current_time_ms)` (`src/core/plc.py`) implements a real scan cycle and its semantics are the load-bearing part of the whole project: **snapshot inputs → evaluate all logic against the snapshot only → commit outputs at end of scan.** Mid-scan input changes are deliberately invisible to that scan. Time is explicit and integer-milliseconds everywhere (`SimulationClock`, `step_ms`); timers derive `dt` from the gap between scan timestamps. Everything is deterministic — the AI layer is advisory and never feeds back into simulation state.

Four rule types are executed: `if_else` (the modern one, produced by the ST parser), plus legacy `assign`, `ton`, and `interlock` rule dicts.

### Data contracts

Layers communicate through plain dicts/JSON, not objects. The recurring shapes:

- **Condition tree** (`st_parser.parse_condition`): `{"op": "AND"|"OR"|"NOT"|"VAR", ...}`. `plc.eval_condition` evaluates it; `plc.condition_label` renders it back to a stable string (`"(X0 AND NOT(X1))"`) — that label is the **coverage key**, so changing the renderer invalidates saved coverage data.
- **Scenario**: `{"name", "initial_inputs", "events": [{"time", "inputs"}], "expected"}` — consumed by `TestHarness.load_scenario`.
- **Property**: `{"name": str, "check": callable(state) -> bool}` where `state` is `{"time", "inputs", "outputs"}`. In config JSON the check is a *lambda source string* that `orchestrator._build_properties` `eval`s — configs are operator-supplied and trusted.
- **Calibration profile**: `{"name", "description", "parameters": {"motor": {...}, "shuttle": {...}, "sensor": {...}}}` — see `outputs/profiles/*.json`.
- **Trace** (`src/bridge/`): either a bare entry list (legacy, treated as unknown provenance) or `{"provenance": {"timestamp": ..., "program": ...}, "entries": [...]}` from `trace_aligner.wrap_trace`. Provenance is load-bearing, not decoration — `align_traces` refuses tolerance 0 on an `arrival_timestamp` trace, and `readable_report` picks its IO map from the declared program and *raises* if handed a map scoped to a different one.
- **State** (`ui/api_server.py` → React): `{"time", "motor_running", "shuttle_position", "sensors": {X0,X1,X2}, "jam_detected"}`.

### Pipeline (`tool/orchestrator.py:run_pipeline`)

`load ST → parse → load calibration profile → build properties → generate scenarios → batch simulate → aggregate → (optional) AI analysis`, returning one result dict that `output_manager` writes as `report.json`, `run_config.json`, and optionally `ai_report.json` into a timestamped `outputs/runs/<name>/<YYYYMMDD_HHMMSS>/`. Every run also appends a line to `outputs/run_log.jsonl` via `run_logger`. `error_handler` wraps config loading and pipeline execution so failures surface as human-readable messages plus exit code 1; violations are advisory and still exit 0.

The pipeline suppresses per-tick stdout by swapping `sys.stdout` for a `StringIO` during batch execution — be aware when debugging.

### Subsystem map

| Path | Role |
|---|---|
| `src/core/` | `st_loader` (read `.st`), `st_parser` (recursive-descent ST → rule dicts), `plc` (scan cycle, TON, coverage), `loom` (crude state), `clock` |
| `src/testing/` | `test_harness` (single-scenario runner + wiring callback), `properties`, `scenario_template` |
| `src/batch/` | `scenario_generator` (deterministic input×timing sweep, `max_scenarios` cap), `batch_executor`, `batch_runner` (many programs, one scenario) |
| `src/analysis/` | `aggregator`, `coverage_gap`, `log_filter` (timeline compression), `analysis_payload` / `export_analysis` (build the JSON the AI layer consumes) |
| `src/ai/` | `ollama_client` (stdlib `urllib` → `/api/generate`), `prompt_builder`, `prompt_limiter` (token budget), `failure_explainer` / `coverage_analyzer` / `scenario_suggester` / `safety_analyzer`, `ai_report` (fans out to all four), `prompt_snapshot` (audit trail of prompts sent) |
| `src/bridge/` | **Standalone, not wired into the CLI.** Compares simulation traces against real-machine traces: `io_map` (program-scoped), `sim_trace` / `real_trace` / `trace_recorder`, `real_adapter` (currently a mock), `trace_aligner` (two-pointer matching + offset diagnostics), `trace_diff` (ticks / transitions modes), `mismatch_report`, `readable_report`, `comparison_export` |
| `loom_twin.py` | High-fidelity twin: `MotorStateMachine` (startup/stop delays), `CyclicShuttleModel`, `PositionSensor`, `DelayedSensor` (delay + miss-every-n noise) |
| `calibration.py` | Measure the twin, compare to real-world targets, iteratively adjust profile parameters, drift detection, `ProfileRegistry`, calibrated-model save/load |

## Conventions

- **Commits are phase/step scoped**: `Phase N Step M: <what> - <specifics>`. The codebase was built phase by phase and module docstrings/`__main__` banners still reference their phase number — keep those references accurate if you move code.
- Module docstrings carry the **schema of what the module returns**. When you change a return shape, update the docstring — downstream layers were written against it.
- Paired `print_*` functions (`print_summary`, `print_aggregation_summary`, `print_errors`, …) sit next to the function that builds the data. Keep formatting out of the computation.
- Generated artefacts under `outputs/runs/` are gitignored; committed profiles in `outputs/profiles/` are not.

## Import offer

A user-level OpenAI Codex config (`~/.codex/config.toml`) and Gemini CLI settings (`~/.gemini/settings.json`) exist on this machine. To bring over MCP servers, slash commands, subagents, skills, or instructions, reply `/import` to scan and list what's importable, then `/import --yes=<digest>` (the scan output names the digest) to apply the user-level items. If `/import` isn't available on this surface, run `claude import` from a terminal.
