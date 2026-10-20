"""Transport freshness uses a nonce and bounded lifetimes in each clock domain."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_clock_controls", ROOT / ".agents/skills/verify-twinaatma/scripts/native_grader_rendezvous.py")
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class NativeClockControls(unittest.TestCase):
    def test_a_separate_kernel_epoch_does_not_invalidate_a_fresh_bounded_exchange(self):
        for start in (1, 1792494841229216000, 4792494841229216000):
            with self.subTest(start=start):
                result = transport.checked_clock_windows({"started_ns": start, "ended_ns": start + 2_000_000_000}, 4_000_000_000)
                self.assertEqual(result["caller_domain"], "linux-monotonic")
                self.assertEqual(result["observer_domain"], "windows-wall")
                self.assertEqual(result["caller_elapsed_ns"], 4_000_000_000)

    def test_impossible_or_unbounded_observer_lifetimes_refuse(self):
        for receipt in ({"started_ns": 0, "ended_ns": 2}, {"started_ns": 2, "ended_ns": 1},
                        {"started_ns": 1, "ended_ns": 1}, {"started_ns": True, "ended_ns": 2},
                        {"started_ns": 1, "ended_ns": 180_000_000_002}, {"started_ns": 1}):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                transport.checked_clock_windows(receipt, 4_000_000_000)

    def test_missing_or_expired_caller_lifetimes_refuse(self):
        for elapsed in (None, True, 0, -1, 300_000_000_001, 1.0):
            with self.subTest(elapsed=elapsed), self.assertRaises(ValueError):
                transport.checked_clock_windows({"started_ns": 1, "ended_ns": 2}, elapsed)


if __name__ == "__main__":
    unittest.main()
