"""Public release must observe policy changes made after result preparation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import unittest
from unittest import mock

from knowledgeos.memory import MemoryAPI, dispatch
from knowledgeos.remembering import RememberingPolicy


class RefreshPolicyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1]
                     / "work/gc-artifacts/.knowledgeos/refresh-policy-controls" / secrets.token_hex(5))
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        self.identity = self.vault / "People/Self.md"
        self.identity.write_bytes(b"# Self\n\n## Heuristics\n\nUnknown.\n")
        self.identity_before = self.identity.read_bytes()
        self.environment = mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.key = os.environ.pop("KNOWLEDGEOS_GATE_KEY", None)
        self.api = MemoryAPI(self.vault)
        self.fact = "The fictional Cedar studio chooses a quiet Friday morning for its planning review."
        captured = self.api.capture("Cedar planning", self.fact)
        self.assertTrue(captured.get("ok"), captured)
        self.path = self.vault / captured["path"]
        self.raw = self.path.read_bytes()
        self.digest = hashlib.sha256(self.raw).hexdigest()
        self.assertTrue(dispatch(self.api, "memory_search", {"query": "Cedar"}).get("ranked"))

    def tearDown(self):
        if self.key is not None:
            os.environ["KNOWLEDGEOS_GATE_KEY"] = self.key
        self.environment.stop()
        self.assertEqual(self.identity.read_bytes(), self.identity_before)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def after_result_preparation(self, action):
        original = self.api._refresh_rows
        done = []

        def refresh(*args, **kwargs):
            rows = original(*args, **kwargs)
            if rows and not done:
                done.append(True)
                action()
            return rows

        with mock.patch.object(self.api, "_refresh_rows", side_effect=refresh):
            result = dispatch(self.api, "memory_search", {"query": "Cedar"})
        self.assertEqual(done, [True], "the public search did not reach result preparation")
        self.assertNotIn(self.fact, json.dumps(result))
        return result

    def test_forgetting_after_rows_are_prepared_prevents_public_release(self):
        def forget():
            result = MemoryAPI(self.vault).forget(self.path.relative_to(self.vault).as_posix(), self.digest)
            self.assertTrue(result.get("ok"), result)

        result = self.after_result_preparation(forget)
        self.assertTrue(result.get("error") or not result.get("ranked"), result)
        refused = self.api.capture("Different title", self.fact)
        self.assertFalse(refused.get("ok"), refused)

    def test_tampering_after_rows_are_prepared_fails_closed_at_public_release(self):
        other = self.api.capture("Birch trial", "The fictional Birch pilot has three short weekly review meetings.")
        other_path = self.vault / other["path"]
        self.assertTrue(self.api.forget(other["path"], hashlib.sha256(other_path.read_bytes()).hexdigest()).get("ok"))

        def tamper():
            authority = RememberingPolicy(self.vault)._authority()
            envelope = json.loads(authority.read_text(encoding="utf-8"))
            envelope["mac"] = "0" * 64
            authority.write_text(json.dumps(envelope), encoding="utf-8")

        result = self.after_result_preparation(tamper)
        self.assertTrue(result.get("error"), result)


if __name__ == "__main__":
    unittest.main()
