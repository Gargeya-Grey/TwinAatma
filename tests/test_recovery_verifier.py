"""Recovery evidence must reject stale quotes, empty proxies and unverifiable refusal."""
import importlib.util
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("recovery_source_proof", SCRIPTS / "recovery.py")
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


def result(frozen=True, fresh=True):
    payload = {"ranked": [{"path": "Concepts/Recovery.md", "snippet": "rq731quote current evidence after an external edit."}]}
    if fresh:
        payload["ranked"].append({"path": "Concepts/Fresh.md", "snippet": "rq731quote new evidence created while indexing is unavailable."})
    if frozen:
        payload.update(index_frozen=True, index_frozen_note="Notes created while the index is frozen may be missing.")
    return {"is_error": False, "payload": payload}


class RecoveryVerifierTests(unittest.TestCase):
    def test_current_quotes_and_disclosure_are_both_required(self):
        good = proof.search_observation(result(), frozen=True)
        silent = proof.search_observation(result(frozen=False), frozen=True)
        self.assertTrue(good["valid"], good)
        self.assertFalse(silent["valid"], silent)
        self.assertFalse(silent["incompleteness_disclosed"])

    def test_stale_quote_cannot_pass_even_with_a_frozen_notice(self):
        candidate = result()
        candidate["payload"]["ranked"][0]["snippet"] = "rq731quote evidence before the editor changes it."
        observed = proof.search_observation(candidate, frozen=True)
        self.assertFalse(observed["valid"], observed)
        self.assertFalse(observed["current_quote"])

    def test_deleted_source_in_any_bucket_prevents_success(self):
        candidate = result()
        candidate["payload"]["title"] = [{"path": "Concepts/Removed.md", "snippet": "deleted"}]
        observed = proof.search_observation(candidate, frozen=True)
        self.assertFalse(observed["valid"], observed)
        self.assertFalse(observed["deleted_note_absent"])

    def test_recovery_requires_the_new_note_and_no_frozen_notice(self):
        for candidate in (result(frozen=False, fresh=False), result(frozen=True)):
            with self.subTest(candidate=candidate):
                self.assertFalse(proof.search_observation(candidate, frozen=False, require_fresh=True)["valid"])
        self.assertTrue(proof.search_observation(result(frozen=False), frozen=False, require_fresh=True)["valid"])

    def test_protocol_error_and_empty_memory_do_not_prove_degraded_recall(self):
        for candidate in ({"is_error": True, "payload": result()["payload"]}, {"is_error": False, "payload": {"index_frozen": True, "index_frozen_note": "Incomplete"}}):
            with self.subTest(candidate=candidate):
                self.assertFalse(proof.search_observation(candidate, frozen=True)["valid"])

    def test_timeout_is_not_a_product_refusal(self):
        action = {"success": False, "stderr": "deadline", "command": {"error": "Command exceeded the proof deadline", "exit_code": -9, "stopped": True}}
        self.assertFalse(proof.refused(action))
        action["command"].update(error=None, exit_code=1)
        action["stderr"] = "the note index is being rebuilt by another process"
        self.assertTrue(proof.refused(action))

    def test_only_a_visible_protocol_error_counts_as_mcp_refusal(self):
        self.assertTrue(proof.refused({"result": {"is_error": True, "payload": {"error": "Self gate is busy; try again"}}}))
        self.assertFalse(proof.refused({"result": {"is_error": False, "payload": {"error": "Self gate is busy"}}}))
        self.assertFalse(proof.refused({"result": {"is_error": True, "payload": {}}}))

    def run_fixture(self, label):
        run = proof.RecoveryRun(ROOT / "work/gc-artifacts/.knowledgeos/recovery-proof-20261019/controls" / uuid.uuid4().hex[:8], "index")
        return run, run.prepare(label)

    def test_actual_missing_database_recovers_current_and_new_source_quotes(self):
        run, fixture = self.run_fixture("missing-positive")
        run.index_case("missing_index", fixture=fixture)
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        self.assertTrue(run.cases[0]["observed"]["retry"]["new_note_recalled"])
        self.assertTrue(all(p["stopped"] and isinstance(p["exit_code"], int) for p in run.processes))

    def test_public_process_silent_search_is_rejected_during_real_obstruction(self):
        run, fixture = self.run_fixture("silent-negative")
        payload = result(frozen=False)["payload"]
        with (fixture["toolkit"] / "knowledgeos/memory.py").open("a", encoding="utf-8") as stream:
            stream.write("\nMemoryAPI.search = lambda self, query, limit=20: " + repr(payload) + "\n")
        run.index_case("blocked_rebuild", fixture=fixture)
        self.assertEqual(run.cases[0]["verdict"], "FAIL", run.cases)
        self.assertFalse(run.cases[0]["observed"]["incompleteness_disclosed"])
        self.assertTrue(run.cases[0]["observed"]["obstruction_preserved"])
        self.assertTrue(all(p["stopped"] for p in run.processes))

    def test_real_sqlite_lock_keeps_a_complete_source_inventory(self):
        run, fixture = self.run_fixture("sqlite-inventory")
        for kind in ("sqlite", "index"):
            with self.subTest(kind=kind):
                holder = run.hold(kind + "-inventory-holder", fixture, kind)
                try:
                    observed = run.snapshot(fixture, kind + "-locked")
                    self.assertEqual(observed["vault/Concepts/Recovery.md"]["sha256"], proof.sha(fixture["vault"] / "Concepts/Recovery.md"))
                    self.assertEqual(observed["vault/knowledge_index.db"]["kind"], "file")
                    self.assertTrue(holder["process"].poll() is None)
                    if kind == "index":
                        self.assertEqual(observed["vault/.knowledgeos/index-rebuild.lock.guard"]["kind"], "file")
                finally:
                    run.stop_holder(holder)
                self.assertTrue(holder["tracked"]["stopped"])

    def test_public_gate_readiness_locates_one_synthetic_owner_scope(self):
        run, fixture = self.run_fixture("gate-readiness")
        identity_before = proof.sha(fixture["vault"] / "People/Self.md")
        path = run.paths_for(fixture, "gate")
        self.assertEqual(path.name, "self-gate.lock")
        self.assertTrue(path.with_name(path.name + ".guard").is_file())
        self.assertTrue(path.resolve().is_relative_to(fixture["scope"].resolve()))
        self.assertEqual(proof.sha(fixture["vault"] / "People/Self.md"), identity_before)
        self.assertTrue(all(p["stopped"] for p in run.processes))


if __name__ == "__main__":
    unittest.main()
