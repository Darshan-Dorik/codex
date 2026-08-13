"""
loom_twin.py — High-Fidelity Behavioral Digital Twin for Circular Loom

Evolves the basic LoomState into a time-based, event-driven behavioral
twin with motor dynamics, shuttle motion, sensor models, and fault logic.

STRICT RULES:
  - No randomness unless explicitly seeded and controlled.
  - No physics engines or 3D rendering.
  - All behavior is deterministic and time-based.
  - Existing loom.py is NOT modified.
"""

# ---------------------------------------------------------------------------
# STEP 1: Motor State Machine
# ---------------------------------------------------------------------------

class MotorState:
    STOPPED  = "STOPPED"
    STARTING = "STARTING"
    RUNNING  = "RUNNING"
    STOPPING = "STOPPING"


class MotorStateMachine:
    """
    Models motor dynamics with startup and stop delays.

    State transitions:
      STOPPED  --[command ON]--> STARTING
      STARTING --[delay elapsed]--> RUNNING
      RUNNING  --[command OFF]--> STOPPING
      STOPPING --[delay elapsed]--> STOPPED

    All times in milliseconds.
    """

    def __init__(self, startup_delay_ms=300, stop_delay_ms=200):
        """
        Args:
            startup_delay_ms : int — time from command ON to RUNNING
            stop_delay_ms    : int — time from command OFF to STOPPED
        """
        self.startup_delay_ms = startup_delay_ms
        self.stop_delay_ms    = stop_delay_ms

        self.state            = MotorState.STOPPED
        self.command_on       = False       # current command from PLC
        self._transition_start_ms = None   # when current transition began

    def command(self, on: bool):
        """Set the motor command (True = run, False = stop)."""
        self.command_on = on

    def update(self, current_time_ms: int):
        """
        Advance the state machine by one tick.

        Args:
            current_time_ms : int — current simulation time in ms

        Returns:
            str — current state after update
        """
        prev_state = self.state

        if self.state == MotorState.STOPPED:
            if self.command_on:
                self.state = MotorState.STARTING
                self._transition_start_ms = current_time_ms

        elif self.state == MotorState.STARTING:
            if not self.command_on:
                # Command withdrawn before startup complete — go back
                self.state = MotorState.STOPPED
                self._transition_start_ms = None
            elif (current_time_ms - self._transition_start_ms
                  >= self.startup_delay_ms):
                self.state = MotorState.RUNNING
                self._transition_start_ms = None

        elif self.state == MotorState.RUNNING:
            if not self.command_on:
                self.state = MotorState.STOPPING
                self._transition_start_ms = current_time_ms

        elif self.state == MotorState.STOPPING:
            if self.command_on:
                # Command restored before stop complete — go back to RUNNING
                self.state = MotorState.RUNNING
                self._transition_start_ms = None
            elif (current_time_ms - self._transition_start_ms
                  >= self.stop_delay_ms):
                self.state = MotorState.STOPPED
                self._transition_start_ms = None

        return self.state

    @property
    def is_running(self):
        """True only when fully in RUNNING state."""
        return self.state == MotorState.RUNNING

    @property
    def is_stopped(self):
        return self.state == MotorState.STOPPED


# ---------------------------------------------------------------------------
# STEP 2: Time-Based Shuttle Motion
# ---------------------------------------------------------------------------

class ShuttleModel:
    """
    Models shuttle position as a function of time.

    Position advances only when the motor is in RUNNING state.
    Units: position in mm (or abstract units), speed in units/second.
    """

    def __init__(self, speed_units_per_sec=100.0):
        """
        Args:
            speed_units_per_sec : float — shuttle travel speed
        """
        self.speed            = speed_units_per_sec
        self.position         = 0.0
        self._last_time_ms    = None

    def update(self, current_time_ms: int, motor_running: bool):
        """
        Advance shuttle position based on elapsed time and motor state.

        Args:
            current_time_ms : int  — current simulation time in ms
            motor_running   : bool — True only when motor is RUNNING

        Returns:
            float — current shuttle position
        """
        if self._last_time_ms is None:
            self._last_time_ms = current_time_ms
            return self.position

        dt_seconds = (current_time_ms - self._last_time_ms) / 1000.0
        self._last_time_ms = current_time_ms

        if motor_running:
            self.position += self.speed * dt_seconds

        return self.position

    def reset(self):
        """Reset position to zero."""
        self.position      = 0.0
        self._last_time_ms = None


# ---------------------------------------------------------------------------
# STEP 3: Cyclic Motion Model
# ---------------------------------------------------------------------------

class CyclicShuttleModel:
    """
    Extends ShuttleModel with circular (wrapping) motion.

    The shuttle travels around a fixed-length track. When position
    reaches cycle_length it wraps back to 0, completing one cycle.

    position is always in [0, cycle_length).
    """

    def __init__(self, speed_units_per_sec=100.0, cycle_length=360.0):
        """
        Args:
            speed_units_per_sec : float — shuttle travel speed
            cycle_length        : float — full cycle distance (e.g. 360 for degrees)
        """
        self.speed         = speed_units_per_sec
        self.cycle_length  = cycle_length
        self.position      = 0.0
        self.cycles_completed = 0        # how many full laps
        self._last_time_ms = None

    def update(self, current_time_ms: int, motor_running: bool):
        """
        Advance position with wrapping.

        Returns:
            float — current position in [0, cycle_length)
        """
        if self._last_time_ms is None:
            self._last_time_ms = current_time_ms
            return self.position

        dt_seconds = (current_time_ms - self._last_time_ms) / 1000.0
        self._last_time_ms = current_time_ms

        if motor_running:
            self.position += self.speed * dt_seconds
            # Wrap and count completed cycles
            while self.position >= self.cycle_length:
                self.position -= self.cycle_length
                self.cycles_completed += 1

        return self.position

    def reset(self):
        """Reset position and cycle count."""
        self.position         = 0.0
        self.cycles_completed = 0
        self._last_time_ms    = None


# ---------------------------------------------------------------------------
# STEP 4: Sensor Model (Position-Based)
# ---------------------------------------------------------------------------

class PositionSensor:
    """
    Models a position-based sensor that activates when the shuttle
    crosses a threshold.

    Sensor is active when position is in [threshold, threshold + window).
    """

    def __init__(self, threshold=180.0, window=20.0):
        """
        Args:
            threshold : float — position where sensor activates
            window    : float — how long sensor stays active (position units)
        """
        self.threshold = threshold
        self.window    = window
        self.active    = False

    def update(self, position: float):
        """
        Update sensor state based on current shuttle position.

        Args:
            position : float — current shuttle position

        Returns:
            bool — sensor active state
        """
        # Sensor active when position in [threshold, threshold + window)
        self.active = (self.threshold <= position < self.threshold + self.window)
        return self.active

    def reset(self):
        """Reset sensor state."""
        self.active = False


# ---------------------------------------------------------------------------
# STEP 5: Sensor Delay + Noise
# ---------------------------------------------------------------------------

class DelayedSensor:
    """
    Wraps a PositionSensor with configurable output delay and
    deterministic missed-trigger behaviour.

    Delay:
      The sensor output is held for delay_ms before being forwarded.
      Internally a ring-buffer of past states is kept.

    Missed triggers:
      If miss_every_n > 0, every Nth activation is suppressed.
      This is deterministic (counter-based), not random.
    """

    def __init__(self, threshold=180.0, window=20.0,
                 delay_ms=0, sim_step_ms=1, miss_every_n=0,
                 step_ms=None):
        """
        Args:
            threshold    : float — position where sensor activates
            window       : float — active zone width
            delay_ms     : int   — output delay in ms; MUST be an exact
                           multiple of sim_step_ms
            sim_step_ms  : int   — PHYSICS integration step, not the PLC
                           scan period. This sensor is a physics-layer
                           object: it is updated every time the shuttle
                           moves, which is finer than the rate the PLC
                           samples it at.
            miss_every_n : int   — suppress every Nth activation (0 = no misses)
            step_ms      : int   — DEPRECATED alias for sim_step_ms

        Raises:
            ValueError — if delay_ms is not an exact multiple of
            sim_step_ms. The buffer length is delay_ms // sim_step_ms,
            so an indivisible delay used to truncate silently: a 50ms
            delay at a 100ms step became NO delay at all, and the
            resulting trace looked plausible. Failing at construction
            makes that a load-time break instead.
        """
        if step_ms is not None:
            sim_step_ms = step_ms

        if sim_step_ms <= 0:
            raise ValueError(f"sim_step_ms must be positive, got {sim_step_ms}")

        if delay_ms % sim_step_ms != 0:
            raise ValueError(
                f"DelayedSensor delay_ms={delay_ms} is not a multiple of "
                f"sim_step_ms={sim_step_ms}: the delay buffer would "
                f"truncate to {delay_ms // sim_step_ms} step(s) "
                f"({(delay_ms // sim_step_ms) * sim_step_ms}ms) and the "
                f"remaining {delay_ms % sim_step_ms}ms would vanish "
                f"silently."
            )

        self.threshold    = threshold
        self.window       = window
        self.delay_ms     = delay_ms
        self.sim_step_ms  = sim_step_ms
        self.step_ms      = sim_step_ms   # legacy attribute name
        self.miss_every_n = miss_every_n

        # Internal position sensor
        self._sensor = PositionSensor(threshold, window)

        # Delay buffer: stores raw sensor states, oldest first
        # Buffer length = delay_ms / sim_step_ms  → exactly delay_ms lag
        # When delay_ms=0, buf_len=1 means 1-tick lag — use 0 for instant
        if delay_ms == 0:
            buf_len = 0
        else:
            buf_len = max(1, delay_ms // sim_step_ms)
        self._buffer = [False] * buf_len

        # Missed trigger tracking
        self._activation_count = 0   # how many times sensor went True
        self._was_active       = False
        self._suppressing      = False

        # Public output
        self.active  = False
        self.delayed = False   # True if currently in delay phase

    def update(self, position: float):
        """
        Update sensor with delay and missed-trigger logic.

        Args:
            position : float — current shuttle position

        Returns:
            bool — sensor output (after delay and miss filtering)
        """
        raw = self._sensor.update(position)

        # Detect rising edge (False → True) for missed-trigger counting
        rising_edge = raw and not self._was_active
        self._was_active = raw

        if rising_edge:
            self._activation_count += 1
            # Decide whether to suppress this entire activation
            if (self.miss_every_n > 0 and
                    self._activation_count % self.miss_every_n == 0):
                self._suppressing = True
            else:
                self._suppressing = False

        # Clear suppression flag when raw goes False
        if not raw:
            self._suppressing = False

        # Apply suppression to the whole window
        filtered = False if self._suppressing else raw

        # Shift delay buffer: append new value, pop oldest as output
        if self._buffer:
            self._buffer.append(filtered)
            output = self._buffer.pop(0)
        else:
            # No delay — output immediately
            output = filtered

        self.active  = output
        self.delayed = (raw != output)   # True when output lags behind raw
        return self.active

    def reset(self):
        """Reset all state."""
        self._sensor.reset()
        self._buffer          = [False] * len(self._buffer)
        self._activation_count = 0
        self._was_active       = False
        self._suppressing      = False
        self.active            = False
        self.delayed           = False


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 8 - Step 5: Sensor Delay + Noise")
    print("=" * 60)

    STEP = 100   # ms per tick

    # -------------------------------------------------------
    # Test 1: sensor with 200ms delay
    # threshold=180, window=20 → raw ON at t=1800ms
    # delayed output ON at t=2000ms (200ms later)
    # -------------------------------------------------------
    print("\nTest 1 — 200ms delay (threshold=180, window=20):")
    motor1   = MotorStateMachine(startup_delay_ms=0, stop_delay_ms=0)
    shuttle1 = CyclicShuttleModel(speed_units_per_sec=100.0, cycle_length=360.0)
    sensor1  = DelayedSensor(threshold=180.0, window=20.0,
                             delay_ms=200, step_ms=STEP)
    motor1.command(True)

    print(f"  {'Time':>6}  {'Position':>10}  {'Raw':>5}  {'Output':>7}  Note")
    print("  " + "-" * 50)

    for t in range(0, 2400, STEP):
        motor1.update(t)
        pos = shuttle1.update(t, motor1.is_running)
        out = sensor1.update(pos)
        raw = sensor1._sensor.active
        note = ""
        if 170 <= pos <= 210 or t in (1800, 1900, 2000, 2100):
            note = "← delayed ON" if (out and not raw) else \
                   "← raw ON" if (raw and not out) else \
                   "← both ON" if (raw and out) else ""
            print(f"  {t:>5}ms  {pos:>9.2f}  "
                  f"{'ON' if raw else 'OFF':>5}  "
                  f"{'ON' if out else 'OFF':>7}  {note}")

    # -------------------------------------------------------
    # Test 2: missed trigger every 2nd activation
    # -------------------------------------------------------
    print("\nTest 2 — Miss every 2nd activation (no delay):")
    motor2   = MotorStateMachine(startup_delay_ms=0, stop_delay_ms=0)
    shuttle2 = CyclicShuttleModel(speed_units_per_sec=100.0, cycle_length=360.0)
    sensor2  = DelayedSensor(threshold=180.0, window=20.0,
                             delay_ms=0, step_ms=STEP, miss_every_n=2)
    motor2.command(True)

    activations = []
    for t in range(0, 8000, STEP):
        motor2.update(t)
        pos = shuttle2.update(t, motor2.is_running)
        out = sensor2.update(pos)
        if out and (not activations or activations[-1][1] != t - STEP):
            activations.append((t, t))
    print(f"  Activations detected: {len(activations)}")
    for a in activations:
        print(f"    t={a[0]}ms")

    # -------------------------------------------------------
    # Assertions
    # -------------------------------------------------------
    print("\n--- Assertions ---")

    # Test 1: delayed output fires 200ms after raw
    m = MotorStateMachine(startup_delay_ms=0, stop_delay_ms=0)
    s = CyclicShuttleModel(speed_units_per_sec=100.0, cycle_length=360.0)
    sen = DelayedSensor(threshold=180.0, window=20.0,
                        delay_ms=200, step_ms=STEP)
    m.command(True)

    raw_on_time    = None
    output_on_time = None

    for t in range(0, 2500, STEP):
        m.update(t)
        pos = s.update(t, m.is_running)
        out = sen.update(pos)
        raw = sen._sensor.active
        if raw and raw_on_time is None:
            raw_on_time = t
        if out and output_on_time is None:
            output_on_time = t

    assert raw_on_time    is not None,  "raw sensor must fire"
    assert output_on_time is not None,  "delayed output must fire"
    assert output_on_time - raw_on_time == 200, \
        f"delay must be 200ms, got {output_on_time - raw_on_time}ms"
    print(f"  PASS — raw fires at t={raw_on_time}ms, "
          f"output fires at t={output_on_time}ms (delay=200ms)")

    # Test 2: miss every 2nd — only odd activations pass through
    m2 = MotorStateMachine(startup_delay_ms=0, stop_delay_ms=0)
    s2 = CyclicShuttleModel(speed_units_per_sec=100.0, cycle_length=360.0)
    sen2 = DelayedSensor(threshold=180.0, window=20.0,
                         delay_ms=0, step_ms=STEP, miss_every_n=2)
    m2.command(True)

    raw_count = 0
    out_count = 0
    prev_raw  = False
    prev_out  = False

    for t in range(0, 12000, STEP):
        m2.update(t)
        pos = s2.update(t, m2.is_running)
        out = sen2.update(pos)
        raw = sen2._sensor.active
        if raw and not prev_raw:
            raw_count += 1
        if out and not prev_out:
            out_count += 1
        prev_raw = raw
        prev_out = out

    # miss_every_n=2: suppress every 2nd activation
    # raw=N activations → suppressed = N//2 → out = N - N//2
    expected_out = raw_count - raw_count // 2
    assert out_count == expected_out, \
        f"output count wrong: raw={raw_count} out={out_count} expected={expected_out}"
    print(f"  PASS — miss every 2nd: raw={raw_count} activations, "
          f"output={out_count} ({raw_count - out_count} suppressed)")

    # Test 3: no delay, no miss → output matches raw exactly
    m3 = MotorStateMachine(startup_delay_ms=0, stop_delay_ms=0)
    s3 = CyclicShuttleModel(speed_units_per_sec=100.0, cycle_length=360.0)
    sen3 = DelayedSensor(threshold=180.0, window=20.0,
                         delay_ms=0, step_ms=STEP, miss_every_n=0)
    m3.command(True)
    for t in range(0, 2500, STEP):
        m3.update(t)
        pos = s3.update(t, m3.is_running)
        out = sen3.update(pos)
        raw = sen3._sensor.active
        assert out == raw, f"no-delay no-miss: output must equal raw at t={t}"
    print("  PASS — no delay, no miss: output matches raw exactly")
