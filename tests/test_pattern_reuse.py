from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import unittest
from unittest import mock

from knowledgeos import remembering


class PatternReuseTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(__file__).resolve().parents[1]
                     / "work/gc-artifacts/.knowledgeos/pattern-reuse" / secrets.token_hex(6))
        self.vault = self.root / "vault"
        self.vault.mkdir(parents=True)
        self.environment = mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.policy = remembering.RememberingPolicy(self.vault)

    def test_complete_text_and_current_metadata_determine_exclusion(self):
        body = "redgrain paper review. " * 2000
        self.assertIsNone(self.policy.text_reason(body))
        self.assertEqual(self.policy.text_reason(body + " API key: syntheticcredential"), "credential_pattern")
        self.assertEqual(self.policy.text_reason(body, {"privacy": "private"}), "explicit_exclusion")
        self.assertEqual(self.policy.text_reason("My colleague takes ｉｎｓｕ\u200bｌｉｎ."), "third_party_pattern")
        self.assertIsNone(self.policy.text_reason(body))

    def test_changed_provider_does_not_reuse_a_previous_allowance(self):
        body = "redgrain paper review."
        self.assertIsNone(self.policy.text_reason(body))
        with mock.patch.object(remembering, "_CREDENTIALS", re.compile(r"\bredgrain\b")):
            self.assertEqual(self.policy.text_reason(body), "credential_pattern")
        self.assertIsNone(self.policy.text_reason(body))
        with mock.patch.object(remembering.unicodedata, "normalize", return_value="My colleague takes insulin."):
            self.assertEqual(self.policy.text_reason(body), "third_party_pattern")
        self.assertIsNone(self.policy.text_reason(body))

    def test_provider_failure_is_not_replaced_with_a_cached_allowance(self):
        body = "redgrain paper review."
        self.assertIsNone(self.policy.text_reason(body))
        provider = mock.Mock()
        provider.search.side_effect = RuntimeError("synthetic classifier failure")
        with mock.patch.object(remembering, "_CREDENTIALS", provider):
            with self.assertRaisesRegex(RuntimeError, "synthetic classifier failure"):
                self.policy.text_reason(body)
        self.assertIsNone(self.policy.text_reason(body))


if __name__ == "__main__":
    unittest.main()
