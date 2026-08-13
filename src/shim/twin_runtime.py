"""
twin_runtime.py — Closed-Loop PLC + Twin Runtime

Runs the loom twin with the PLC IN THE LOOP, at two rates.

WHY THE PLC IS IN THE LOOP
--------------------------
`ui/api_server.py` previously ran the twin OPEN-loop: it commanded the
motor directly (`motor.command(True)`) and injected a jam on a timer.
No PLC was ever instantiated, so the state it exposed contained only
X-side signals — there were no Y outputs at all.

That makes the twin unusable as a bench target. `src/bridge/trace_diff`
compares sim `inputs + outputs` against real `signals`, and every
mismatch case in the bridge is an OUTPUT (Y0). A collector polling an
open-loop twin can never produce a trace that diffs meaningfully
against a sim trace, because half the signals do not exist.

Here the loop is closed:

    twin sensors ──► PLC inputs ──► PLC.scan() ──► PLC outputs ──► motor

so Y0/Y1 exist, are driven by the same ST program the simulator runs,
and are pollable over a fieldbus.

TWO RATES, NOT ONE
------------------
`sim_step_ms` integrates the twin's physics. `scan_period_ms` is how
often the PLC samples it. They must differ, and by a real margin:

    if sim_step_ms == scan_period_ms the split is a rename — the PLC
    sees every physics update and NO SUB-SCAN EVENT CAN EXIST.

A real sensor pulse can begin and end between two scans, and a real
PLC misses it. That behaviour only exists if physics is integrated
finer than the controller samples. Defaults are sim_step_ms=1 and
scan_period_ms=10 (10:1); the constructor enforces a 10:1 minimum and
exact divisibility.

Physics at 1ms is ~100x the arithmetic of the old 100ms loop, which is
irrelevant — it is a handful of float operations per step.

TRACES RECORD AT SCAN RATE
--------------------------
Trace entries are emitted once per SCAN, not once per sim step. This
is deliberate and load-bearing for anything long-running:

    7-day soak @ scan rate (10ms)  ≈  60M entries
    7-day soak @ sim rate  (1ms)   ≈  600M entries

Recording at sim rate would also be dishonest — it would claim
observations the controller never made. A collector cannot see between
scans, so neither does the trace.

SAFETY
------
Read-only with respect to anything real. This module drives a
simulation and nothing else.
"""

import os
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
for _sub in ("", "src/core", "src/bridge"):
    _p = os.path.join(_ROOT, _sub) if _sub else _ROOT
    if _p not in sys.path:
        sys.path.insert(0, _p)

from plc import PLC
from st_loader import load_st_file
from st_parser import parse_st
from loom_twin import MotorStateMachine, CyclicShuttleModel, DelayedSensor


MIN_RATE_RATIO = 10

DEFAULT_PROFILE = {
    "name": "api_server_legacy",
    "description": "Matches the speed ui/api_server.py ran the twin at",
    "parameters": {
        "motor":   {"startup_delay_ms": 300, "stop_delay_ms": 200},
        "shuttle": {"speed_units_per_sec": 60.0, "cycle_length": 360.0},
        "sensor":  {"threshold": 180.0, "window": 20.0,
                    "delay_ms": 0, "miss_every_n": 0},
    },
}


class TwinRuntime:
    """
    PLC + twin, closed loop, dual rate.

    The runtime owns the only mutable state and hands out immutable
    snapshots, so an HTTP handler and a Modbus server can read the same
    tick without either of them touching the simulation.
    """

    def __init__(self, logic, profile=None,
                 sim_step_ms=1, scan_period_ms=10,
                 jam_at_cycle=2, jam_duration_ms=3000,
                 program=None, run_command=True):
        """
        Args:
            logic           : list — parsed ST logic from parse_st()
            profile         : dict | None — calibration profile
            sim_step_ms     : int — physics integration step
            scan_period_ms  : int — PLC scan period; must be an exact
                              multiple of sim_step_ms, ratio >= 10
            jam_at_cycle    : int | None — inject a jam once the shuttle
                              has completed this many cycles
            jam_duration_ms : int — how long the jam holds
            program         : str | None — ST program path, recorded as
                              trace provenance. Symbols are meaningless
                              without it.
            run_command     : bool — initial state of X0
        """
        if sim_step_ms <= 0:
            raise ValueError(f"sim_step_ms must be positive, got {sim_step_ms}")
        if scan_period_ms % sim_step_ms != 0:
            raise ValueError(
                f"scan_period_ms={scan_period_ms} must be an exact "
                f"multiple of sim_step_ms={sim_step_ms}"
            )
        ratio = scan_period_ms // sim_step_ms
        if ratio < MIN_RATE_RATIO:
            raise ValueError(
                f"scan_period_ms/sim_step_ms = {ratio}:1 is too coarse. "
                f"Below {MIN_RATE_RATIO}:1 the split is a rename — the "
                f"PLC sees essentially every physics update and no "
                f"sub-scan sensor pulse can exist."
            )

        self.sim_step_ms    = sim_step_ms
        self.scan_period_ms = scan_period_ms
        self.rate_ratio     = ratio
        self.program        = program

        profile = profile or DEFAULT_PROFILE
        self.profile = profile
        p = profile["parameters"]

        self.motor = MotorStateMachine(
            startup_delay_ms=p["motor"]["startup_delay_ms"],
            stop_delay_ms=p["motor"]["stop_delay_ms"])
        self.shuttle = CyclicShuttleModel(
            speed_units_per_sec=p["shuttle"]["speed_units_per_sec"],
            cycle_length=p["shuttle"]["cycle_length"])
        self.sensor = DelayedSensor(
            threshold=p["sensor"]["threshold"],
            window=p["sensor"]["window"],
            delay_ms=p["sensor"]["delay_ms"],
            sim_step_ms=sim_step_ms,
            miss_every_n=p["sensor"]["miss_every_n"])

        self.plc = PLC()
        self.plc.logic = logic
        self.plc.inputs = {"X0": bool(run_command), "X1": False, "X2": False}

        self.jam_at_cycle    = jam_at_cycle
        self.jam_duration_ms = jam_duration_ms
        self._jam_start_ms   = None
        self._jam_done       = False

        self.t_ms       = 0
        self.scan_count = 0
        self._lock      = threading.Lock()
        self._snapshot  = self._build_snapshot(jam_active=False)

    # -----------------------------------------------------------------
    # Simulation
    # -----------------------------------------------------------------

    def step(self):
        """
        Advance the runtime by one SIM step.

        Physics moves every step. The PLC scans only on scan
        boundaries, so a sensor pulse narrower than scan_period_ms can
        rise and fall entirely between two scans and never be seen —
        which is what a real controller does.

        Returns:
            bool — True if this step included a PLC scan
        """
        self.t_ms += self.sim_step_ms

        jam_active = self._update_jam()

        # --- physics ---
        self.motor.update(self.t_ms)
        position = self.shuttle.update(self.t_ms, self.motor.is_running)
        sensor_active = self.sensor.update(position)

        scanned = (self.t_ms % self.scan_period_ms == 0)
        if scanned:
            # --- sample the machine into PLC inputs ---
            self.plc.inputs["X1"] = sensor_active
            self.plc.inputs["X2"] = jam_active

            self.plc.scan(self.t_ms)
            self.scan_count += 1

            # --- drive the machine from PLC outputs ---
            # Y0 is the motor contactor. The command reaches the motor
            # one scan after the condition that caused it, which is why
            # the machine overruns a jam by one scan period.
            self.motor.command(bool(self.plc.outputs.get("Y0", False)))

            with self._lock:
                self._snapshot = self._build_snapshot(jam_active)

        return scanned

    def step_scan(self):
        """Advance exactly one scan period (rate_ratio sim steps)."""
        for _ in range(self.rate_ratio):
            self.step()

    def run_until(self, end_ms):
        """
        Run to end_ms and return the recorded trace.

        The trace has one entry per SCAN — see the module docstring.
        """
        trace = []
        while self.t_ms < end_ms:
            if self.step():
                trace.append(self.trace_entry())
        return trace

    def _update_jam(self):
        """Deterministic jam injection, counted in shuttle cycles."""
        if self.jam_at_cycle is None or self._jam_done:
            return False

        if (self._jam_start_ms is None and
                self.shuttle.cycles_completed >= self.jam_at_cycle):
            self._jam_start_ms = self.t_ms

        if self._jam_start_ms is None:
            return False

        if self.t_ms < self._jam_start_ms + self.jam_duration_ms:
            return True

        self._jam_done = True
        return False

    # -----------------------------------------------------------------
    # Observation
    # -----------------------------------------------------------------

    def _build_snapshot(self, jam_active):
        return {
            "time":             self.t_ms,
            "motor_running":    self.motor.is_running,
            "shuttle_position": round(self.shuttle.position, 2),
            "sensors":          dict(self.plc.inputs),
            "jam_detected":     jam_active,
            # additive — the React dashboard reads the five keys above
            "outputs":          dict(self.plc.outputs),
            "motor_state":      self.motor.state,
            "scan_count":       self.scan_count,
            "cycles_completed": self.shuttle.cycles_completed,
        }

    def snapshot(self):
        """Return the latest scan's state. Safe from any thread."""
        with self._lock:
            return dict(self._snapshot)

    def trace_entry(self):
        """
        One trace entry for the current scan, in sim_trace shape.

        Separate inputs/outputs so this drops straight into
        trace_diff without translation.
        """
        return {
            "time":    self.t_ms,
            "inputs":  dict(self.plc.inputs),
            "outputs": dict(self.plc.outputs),
        }

    # -----------------------------------------------------------------
    # Threading
    # -----------------------------------------------------------------

    def run_forever(self, stop_event=None):
        """
        Free-running loop against the wall clock.

        Sim time is authoritative; the sleep only paces it. Every
        deterministic path goes through step()/run_until() instead, so
        the self-tests never touch a clock.
        """
        import time as _time
        next_wall = _time.monotonic()
        while stop_event is None or not stop_event.is_set():
            self.step_scan()
            next_wall += self.scan_period_ms / 1000.0
            delay = next_wall - _time.monotonic()
            if delay > 0:
                _time.sleep(delay)
            else:
                next_wall = _time.monotonic()

    def start_thread(self):
        """Start run_forever on a daemon thread. Returns (thread, stop_event)."""
        stop_event = threading.Event()
        t = threading.Thread(target=self.run_forever, args=(stop_event,),
                             daemon=True)
        t.start()
        return t, stop_event


def make_runtime(program="programs/shuttle_control.st", **kwargs):
    """
    Build a TwinRuntime from an ST program path.

    Defaults to shuttle_control.st because that is the program the twin
    actually implements: loom_twin models a position sensor and a jam
    condition and has NO fault sensor, so motor_start.st's X1 has no
    counterpart in the machine.
    """
    path = program if os.path.isabs(program) else os.path.join(_ROOT, program)
    logic = parse_st(load_st_file(path))
    return TwinRuntime(logic, program=program, **kwargs)


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 11 - Step 4: Closed-Loop Twin Runtime")
    print("=" * 60)

    # -------------------------------------------------------
    # Test 1: rate split is enforced
    # -------------------------------------------------------
    print("\nTest 1 — Rate split enforcement:")
    logic = parse_st(load_st_file(
        os.path.join(_ROOT, "programs/shuttle_control.st")))

    rate_errors = {}
    for label, kw in (
        ("equal rates (1:1)",   dict(sim_step_ms=10, scan_period_ms=10)),
        ("too coarse (5:1)",    dict(sim_step_ms=2,  scan_period_ms=10)),
        ("not divisible",       dict(sim_step_ms=3,  scan_period_ms=10)),
    ):
        try:
            TwinRuntime(logic, **kw)
            rate_errors[label] = None
        except ValueError as exc:
            rate_errors[label] = str(exc)
        print(f"  {label:20} → "
              f"{'rejected' if rate_errors[label] else 'ACCEPTED'}")

    rt = TwinRuntime(logic, sim_step_ms=1, scan_period_ms=10)
    print(f"  {'10:1':20} → accepted (ratio {rt.rate_ratio}:1)")

    # -------------------------------------------------------
    # Test 2: the loop is closed — outputs exist
    # -------------------------------------------------------
    print("\nTest 2 — Closed loop produces outputs:")
    rt = make_runtime(jam_at_cycle=None)
    trace = rt.run_until(1000)
    print(f"  {len(trace)} scans in 1000ms at {rt.scan_period_ms}ms")
    print(f"  first entry : {trace[0]}")
    print(f"  last entry  : {trace[-1]}")

    # -------------------------------------------------------
    # Test 3: traces record at scan rate, not sim rate
    # -------------------------------------------------------
    print("\nTest 3 — Trace rate:")
    rt3 = make_runtime(jam_at_cycle=None)
    trace3 = rt3.run_until(1000)
    sim_steps = 1000 // rt3.sim_step_ms
    print(f"  sim steps taken   : {sim_steps}")
    print(f"  trace entries     : {len(trace3)}")
    print(f"  ratio             : {sim_steps // len(trace3)}:1")

    # -------------------------------------------------------
    # Test 4: sub-scan pulses can be missed (the point of the split)
    # -------------------------------------------------------
    print("\nTest 4 — Sub-scan sensor pulse:")
    # window/speed = pulse width. 3 units at 600 u/s = 5ms — half a
    # scan period, so the PLC can step right over it.
    narrow = {
        "name": "narrow-pulse",
        "description": "sensor pulse narrower than one scan period",
        "parameters": {
            "motor":   {"startup_delay_ms": 0, "stop_delay_ms": 0},
            "shuttle": {"speed_units_per_sec": 600.0, "cycle_length": 360.0},
            "sensor":  {"threshold": 180.0, "window": 3.0,
                        "delay_ms": 0, "miss_every_n": 0},
        },
    }
    rt4 = TwinRuntime(logic, profile=narrow, sim_step_ms=1,
                      scan_period_ms=10, jam_at_cycle=None)

    raw_pulses, seen_by_plc = 0, 0
    prev_raw = prev_seen = False
    for _ in range(6000):
        scanned = rt4.step()
        raw = rt4.sensor.active
        if raw and not prev_raw:
            raw_pulses += 1
        prev_raw = raw
        if scanned:
            seen = rt4.plc.inputs["X1"]
            if seen and not prev_seen:
                seen_by_plc += 1
            prev_seen = seen

    pulse_ms = narrow["parameters"]["sensor"]["window"] / \
        narrow["parameters"]["shuttle"]["speed_units_per_sec"] * 1000
    print(f"  pulse width       : {pulse_ms:.1f}ms "
          f"(scan period {rt4.scan_period_ms}ms)")
    print(f"  pulses in physics : {raw_pulses}")
    print(f"  pulses seen by PLC: {seen_by_plc}")
    print(f"  missed            : {raw_pulses - seen_by_plc}")

    # -------------------------------------------------------
    # Test 5: determinism
    # -------------------------------------------------------
    print("\nTest 5 — Determinism (no wall clock in step()):")
    a = make_runtime().run_until(20000)
    b = make_runtime().run_until(20000)
    print(f"  two independent runs of {len(a)} scans → "
          f"{'identical' if a == b else 'DIFFERENT'}")

    # -------------------------------------------------------
    # Test 6: jam handling through the PLC
    # -------------------------------------------------------
    print("\nTest 6 — Jam stops the motor via Y0, not directly:")
    rt6 = make_runtime()
    scans6 = []
    while rt6.t_ms < 30000:
        if rt6.step():
            s = rt6.snapshot()
            scans6.append({
                "time":          s["time"],
                "X0":            s["sensors"]["X0"],
                "X2":            s["sensors"]["X2"],
                "Y0":            s["outputs"].get("Y0"),
                "motor_running": s["motor_running"],
            })

    i_jam    = next(i for i, s in enumerate(scans6) if s["X2"])
    jam_scan = scans6[i_jam]
    next_scan = scans6[i_jam + 1]

    print(f"  {'t':>9}  {'X0':>6} {'X2':>6} {'Y0':>6}  motor_running")
    for s in scans6[i_jam - 1:i_jam + 3]:
        print(f"  {s['time']:>7}ms  {str(s['X0']):>6} {str(s['X2']):>6} "
              f"{str(s['Y0']):>6}  {s['motor_running']}")
    print("  Y0 falls in the SAME scan X2 is sampled — the PLC samples and")
    print("  evaluates within one scan, so the logic adds no latency.")
    print("  motor_running still reads True in that scan: physics for the")
    print("  step already ran before the scan committed the new command, so")
    print("  the motor turns over 1 sim step later and the change is first")
    print(f"  VISIBLE one scan ({rt6.scan_period_ms}ms) on.")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    for label in ("equal rates (1:1)", "too coarse (5:1)", "not divisible"):
        assert rate_errors[label] is not None, f"{label} must be rejected"
    assert "rename" in rate_errors["equal rates (1:1)"]
    print("  PASS — Test 1: 1:1, 5:1 and indivisible rates all rejected")

    assert trace[0]["outputs"], "closed loop must produce outputs"
    assert "Y0" in trace[-1]["outputs"], "Y0 must exist"
    assert "Y1" in trace[-1]["outputs"], "Y1 must exist"
    print("  PASS — Test 2: Y0 and Y1 exist (open loop had no outputs at all)")

    assert len(trace3) == 1000 // rt3.scan_period_ms, \
        "one entry per scan, not per sim step"
    assert len(trace3) * rt3.rate_ratio == sim_steps, \
        "trace must be scan-rate, not sim-rate"
    print(f"  PASS — Test 3: {len(trace3)} entries for {sim_steps} sim steps "
          f"(scan rate, {rt3.rate_ratio}x fewer)")

    assert raw_pulses > 0, "physics must produce pulses"
    assert seen_by_plc < raw_pulses, \
        ("a sub-scan pulse must be missable — if every pulse is seen, "
         "physics is not finer than the scan and the split is a rename")
    print(f"  PASS — Test 4: {raw_pulses - seen_by_plc} of {raw_pulses} "
          f"sub-scan pulses missed by the PLC, as a real controller would")

    assert a == b, "runtime must be deterministic"
    print(f"  PASS — Test 5: {len(a)} scans identical across two runs")

    assert jam_scan["Y0"] is False, \
        "Y0 must fall in the same scan X2 is sampled — the PLC samples " \
        "and evaluates within one scan, so there is no logic latency"
    assert jam_scan["motor_running"] is True, \
        "motor_running still reads True in that scan: its physics ran " \
        "before the scan committed the command"
    assert next_scan["motor_running"] is False, \
        "and must have dropped by the following scan"
    assert next_scan["time"] - jam_scan["time"] == rt6.scan_period_ms
    assert jam_scan["X0"] is True, \
        "X0 must stay asserted during a jam — the open-loop twin dropped " \
        "X0 itself, which was it cheating"
    print(f"  PASS — Test 6: Y0 falls same-scan (t={jam_scan['time']}ms); "
          f"motor visibly stops one scan later "
          f"(t={next_scan['time']}ms); X0 stays asserted")

    # DelayedSensor divisibility, asserted against sim_step_ms
    div_err = None
    try:
        DelayedSensor(delay_ms=25, sim_step_ms=10)
    except ValueError as exc:
        div_err = str(exc)
    assert div_err is not None, "indivisible sensor delay must raise"
    assert "vanish silently" in div_err
    DelayedSensor(delay_ms=25, sim_step_ms=1)     # fine at 1ms physics
    print("  PASS — DelayedSensor rejects an indivisible delay "
          "(25ms @ 10ms step) and accepts it at 1ms")
