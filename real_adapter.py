"""
real_adapter.py — Real Data Adapter (Mock Implementation)

Provides a read_real_signals() interface that will eventually connect
to a real PLC or machine, but for now returns mock data for testing.

SAFETY RULES:
  - This adapter is READ-ONLY — it never writes to the real machine.
  - All data is treated as external input only.
  - No automatic control or feedback into the real machine.

Future implementations can replace MockRealAdapter with a real
Modbus/OPC-UA/Ethernet-IP client without changing the interface.
"""

import time


class MockRealAdapter:
    """
    Mock implementation of a real PLC data adapter.

    Simulates reading signals from a real machine by returning
    pre-programmed values or values from a playback trace.
    """

    def __init__(self, mode="static", playback_trace=None):
        """
        Args:
            mode           : str  — "static" | "playback"
            playback_trace : list — real trace entries (for playback mode)
        """
        self.mode = mode
        self.playback_trace = playback_trace or []
        self.playback_index = 0
        self.start_time_ms  = None

    def read_signals(self):
        """
        Read all signals from the (mock) real machine.

        Returns:
            dict — {symbol: bool} for all signals
        """
        if self.mode == "static":
            # Return fixed values for testing
            return {
                "X0": True,
                "X1": False,
                "X2": False,
                "Y0": True,
                "Y1": False
            }

        elif self.mode == "playback":
            # Play back from a pre-recorded trace
            if self.start_time_ms is None:
                self.start_time_ms = int(time.time() * 1000)

            elapsed_ms = int(time.time() * 1000) - self.start_time_ms

            # Find the closest trace entry by time
            if self.playback_index < len(self.playback_trace):
                entry = self.playback_trace[self.playback_index]
                if elapsed_ms >= entry["time"]:
                    self.playback_index += 1
                return dict(entry.get("signals", {}))
            else:
                # End of trace — return last entry
                if self.playback_trace:
                    return dict(self.playback_trace[-1].get("signals", {}))
                return {}

        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def reset(self):
        """Reset playback state (for playback mode)."""
        self.playback_index = 0
        self.start_time_ms  = None


def read_real_signals(adapter=None):
    """
    Convenience function: read signals from an adapter.

    Args:
        adapter : MockRealAdapter | None — if None, creates a default static adapter

    Returns:
        dict — {symbol: bool}
    """
    if adapter is None:
        adapter = MockRealAdapter(mode="static")
    return adapter.read_signals()


if __name__ == "__main__":
    import json

    print("=" * 60)
    print("Phase 7 - Step 4: Real Data Adapter (Mock)")
    print("=" * 60)

    # --- Test 1: static mode ---
    print("\nTest 1 — Static mode (fixed values):")
    adapter_static = MockRealAdapter(mode="static")
    for i in range(3):
        signals = adapter_static.read_signals()
        print(f"  Read {i+1}: {signals}")

    # --- Test 2: playback mode ---
    print("\nTest 2 — Playback mode (from trace):")
    playback_data = [
        {"time": 0,   "signals": {"X0": False, "Y0": False}},
        {"time": 100, "signals": {"X0": True,  "Y0": False}},
        {"time": 200, "signals": {"X0": True,  "Y0": True}},
        {"time": 300, "signals": {"X0": True,  "Y0": True}},
    ]
    adapter_playback = MockRealAdapter(mode="playback",
                                       playback_trace=playback_data)

    print("  Simulating time progression:")
    for i in range(5):
        signals = adapter_playback.read_signals()
        print(f"    tick {i}: {signals}")
        time.sleep(0.12)  # 120ms between reads

    # --- Test 3: convenience function ---
    print("\nTest 3 — Convenience function (default adapter):")
    signals = read_real_signals()
    print(f"  read_real_signals() → {signals}")

    # --- Test 4: reset playback ---
    print("\nTest 4 — Reset playback:")
    adapter_playback.reset()
    signals_after_reset = adapter_playback.read_signals()
    print(f"  After reset: {signals_after_reset}")

    # --- Assertions ---
    print("\n--- Assertions ---")

    # Static mode returns same values every time
    s1 = adapter_static.read_signals()
    s2 = adapter_static.read_signals()
    assert s1 == s2,                            "static mode must be deterministic"
    print("  PASS — static mode returns identical values")

    # Playback mode advances through trace
    adapter_pb2 = MockRealAdapter(mode="playback",
                                  playback_trace=playback_data)
    first = adapter_pb2.read_signals()
    assert first == playback_data[0]["signals"], "playback starts at index 0"
    print("  PASS — playback mode starts at first entry")

    # Reset works
    assert signals_after_reset == playback_data[0]["signals"], "reset returns to start"
    print("  PASS — reset() returns playback to start")

    # Convenience function works
    assert isinstance(signals, dict),           "must return dict"
    assert len(signals) > 0,                    "must have signals"
    print("  PASS — read_real_signals() returns non-empty dict")
