"""Synthetic adapter controls. These records earn no product acceptance credit."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


metric = load("move_matrix_controls", "acceptance.py")
bridge = load("move_transport_controls", "advanced_host_native.py")


def row(kind, verdict="PASS", suffix="1"):
    expected = "A same-device vault move preserves note/link content, retrieval and declared host wiring."
    return {"path": "synthetic-" + kind + suffix, "report_sha256": suffix * 64,
            "artifact_cell": ["Windows", kind], "artifact_sha256": ("a" if kind == "wheel" else "b") * 64,
            "scope": "artifact", "producer": "verify-twinaatma.native-installed-move-grade/v2",
            "eligible_outcomes": ["PORT.same_device_move"], "model_calls": 0, "verdict": verdict,
            "checks": {"port.same_device_move": {"id": "port.same_device_move", "verdict": verdict, "expected": expected}},
            "native_bridge": {"operation": "installed-move", "binding": {"report_sha256": suffix * 64}}}


class InstalledMoveMatrixControls(unittest.TestCase):
    def verdict(self, rows):
        return metric.installed_move_matrix(rows)["checks"]["port.same_device_move"]["verdict"]

    def test_one_passing_artifact_awards_nothing(self):
        self.assertEqual(self.verdict([row("wheel")]), "NOT CHECKED")
        self.assertEqual(self.verdict([row("binary")]), "NOT CHECKED")

    def test_both_cells_map_only_existing_port_outcome(self):
        result = metric.installed_move_matrix([row("wheel"), row("binary", suffix="2")])
        self.assertEqual(set(result["checks"]), {"port.same_device_move"})
        self.assertEqual(result["checks"]["port.same_device_move"]["verdict"], "PASS")
        self.assertEqual(result["scope"], "artifact")

    def test_a_supplied_failed_run_cannot_be_averaged_away(self):
        self.assertEqual(self.verdict([row("wheel", "FAIL"), row("wheel", suffix="3"), row("binary", suffix="2")]), "FAIL")

    def test_conflicting_bytes_for_one_cell_refuse(self):
        changed = row("wheel", suffix="3")
        changed["artifact_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "conflicting artifact bytes"):
            self.verdict([row("wheel"), changed, row("binary", suffix="2")])

    def test_duplicate_original_report_refuses(self):
        with self.assertRaisesRegex(ValueError, "repeats"):
            self.verdict([row("wheel"), row("wheel")])

    def test_unknown_scope_extra_credit_and_stale_native_binding_refuse(self):
        mutations = ({"scope": "real_host"}, {"eligible_outcomes": ["PORT.same_device_move", "IDENTITY.owner_exact_approval"]},
                     {"artifact_cell": ["Linux", "wheel"]}, {"model_calls": 1},
                     {"native_bridge": {"operation": "score", "binding": {"report_sha256": "1" * 64}}},
                     {"native_bridge": {"operation": "installed-move", "binding": {"report_sha256": "0" * 64}}})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = deepcopy(row("wheel"))
                changed.update(mutation)
                with self.assertRaises(ValueError):
                    self.verdict([changed, row("binary", suffix="2")])

    def test_unknown_transport_operation_refuses_before_any_file_access(self):
        with self.assertRaisesRegex(ValueError, "Unknown bridge operation"):
            bridge.make_request(Path("does-not-exist.json"), {}, "arbitrary-module")

    def test_transport_registry_keeps_advanced_and_move_operations_separate(self):
        self.assertEqual(bridge.NATIVE_FLAGS, {"score": "--native", "infrastructure-probe": "--probe-native", "installed-move": "--native-move"})
        self.assertEqual(bridge.PRODUCER, "verify-twinaatma.advanced-host-staged/v2")


if __name__ == "__main__":
    unittest.main()
