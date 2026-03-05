from __future__ import annotations

import unittest

from src.infra import runtime_state


class RuntimeStateTests(unittest.TestCase):
    def test_uptime_and_started_at_are_exposed(self) -> None:
        self.assertGreaterEqual(runtime_state.uptime_seconds(), 0)
        self.assertRegex(runtime_state.uptime_human(), r"^\d{2}:\d{2}:\d{2}$")
        self.assertIn("T", runtime_state.started_at_iso())

    def test_record_error_updates_last_error(self) -> None:
        runtime_state.record_error("unit-test-error")
        message, timestamp = runtime_state.last_error()
        self.assertIn("unit-test-error", message)
        self.assertIn("T", timestamp)


if __name__ == "__main__":
    unittest.main()
