"""Public memory behavior when policy mirrors and trusted state are damaged."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import unittest
from unittest import mock

from knowledgeos.memory import MemoryAPI
from knowledgeos.textio import atomic_write_bytes


class PrivacyAuthorityTests(unittest.TestCase):
    def setUp(self):
        checkout = Path(__file__).resolve().parents[1]
        fixture_root = Path(os.environ.get("TWINATMA_PRIVACY_TEST_ROOT") or
                            checkout / "work/gc-artifacts/.knowledgeos/privacy-authority-tests")
        self.root = fixture_root / secrets.token_hex(4)
        self.vault = self.root / "vault"
        (self.vault / "People").mkdir(parents=True)
        self.identity = self.vault / "People/Self.md"
        self.identity.write_bytes(b"# Self\n\n## Heuristics\n\n_Unknown._\n")
        self.identity_before = self.identity.read_bytes()
        (self.vault / ".knowledgeos-vault.json").write_text(json.dumps({"vault_id": secrets.token_hex(16)}), encoding="utf-8")
        (self.vault / "Projects").mkdir()
        self.sources = {}
        for name, body in {"old": "Alder release reviews happen on Tuesday mornings.",
                           "current": "Alder release reviews happen on Friday afternoons.",
                           "other": "Birch development planning uses short Monday meetings."}.items():
            path = self.vault / f"Projects/{name}.md"
            path.write_bytes(("# " + name + "\n\n" + body + "\n").encode("utf-8"))
            self.sources[name] = path.read_bytes()
        self.env = mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.root / "state")}, clear=False)
        self.env.start()
        self.override = os.environ.pop("KNOWLEDGEOS_GATE_KEY", None)
        self.api = MemoryAPI(self.vault)
        self.mirror = self.vault / ".knowledgeos/remembering-policy.json"

    def tearDown(self):
        if self.override is not None:
            os.environ["KNOWLEDGEOS_GATE_KEY"] = self.override
        self.env.stop()
        self.assertEqual(self.identity_before, self.identity.read_bytes(), "identity bytes changed")
        for name, before in self.sources.items():
            self.assertEqual(before, (self.vault / f"Projects/{name}.md").read_bytes(), "source bytes changed")

    def sha(self, name):
        return hashlib.sha256(self.sources[name]).hexdigest()

    def forget(self, name="old"):
        return self.api.forget(f"Projects/{name}.md", self.sha(name))

    def corrected(self):
        result = self.api.supersede("Projects/old.md", self.sha("old"), "Projects/current.md", self.sha("current"))
        self.assertTrue(result.get("ok"), result)

    def authority(self):
        paths = list((self.root / "state/vaults").glob("*/remembering-policy.json"))
        self.assertEqual(len(paths), 1)
        return paths[0]

    def retain(self, path, label):
        retained = self.root / "retained" / label
        retained.parent.mkdir(exist_ok=True)
        path.rename(retained)
        return retained

    def assert_closed(self, result):
        self.assertTrue(result.get("error"), result)
        self.assertNotIn("Tuesday", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_missing_mirror_keeps_forgetting_and_permitted_reads(self):
        self.assertTrue(self.forget().get("ok"))
        self.retain(self.mirror, "missing-mirror.json")
        self.assert_closed(MemoryAPI(self.vault).get_note("Projects/old.md"))
        self.assertIn("Birch", MemoryAPI(self.vault).get_note("Projects/other.md")["body"])
        self.assertFalse(self.api.capture("Copied fact", "Alder release reviews happen on Tuesday mornings.").get("ok"))
        self.assertTrue(self.forget().get("ok"))
        self.assertEqual(self.mirror.read_bytes(), self.authority().read_bytes())

    def test_missing_mirror_keeps_historical_attribution(self):
        self.corrected()
        self.retain(self.mirror, "correction-mirror.json")
        historical = MemoryAPI(self.vault).get_note("Projects/old.md")
        self.assertEqual(historical.get("memory_status"), "historical")
        self.assertEqual(historical.get("superseded_by"), "Projects/current.md")
        ranked = self.api.search("Alder").get("ranked", [])
        self.assertNotIn("Projects/old.md", [row["path"] for row in ranked])
        self.assertIn("Projects/current.md", [row["path"] for row in ranked])

    def test_valid_rewrite_of_mirror_is_not_new_authority(self):
        self.assertTrue(self.forget().get("ok"))
        self.retain(self.mirror, "signed-mirror.json")
        altered = b'{"version":1,"forgotten":{},"superseded":{}}'
        self.mirror.write_bytes(altered)
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assert_closed(self.api.capture("New fact", "Birch prefers simple release notes."))
        self.assertEqual(altered, self.mirror.read_bytes())

    def test_replayed_previous_signed_mirror_cannot_undo_latest_forgetting(self):
        self.assertTrue(self.forget().get("ok"))
        prior = self.mirror.read_bytes()
        self.assertTrue(self.forget("other").get("ok"))
        self.retain(self.mirror, "latest-mirror.json")
        self.mirror.write_bytes(prior)
        self.assert_closed(MemoryAPI(self.vault).get_note("Projects/other.md"))
        self.assertTrue(self.forget("other").get("ok"))
        self.assertEqual(self.mirror.read_bytes(), self.authority().read_bytes())

    def test_missing_trusted_authority_is_not_adopted_from_signed_mirror(self):
        self.assertTrue(self.forget().get("ok"))
        authority = self.authority()
        self.retain(authority, "authority-missing.json")
        original = self.mirror.read_bytes()
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assert_closed(self.forget())
        self.assertFalse(authority.exists())
        self.assertEqual(original, self.mirror.read_bytes())

    def test_changed_vault_marker_cannot_relocate_signed_policy(self):
        self.assertTrue(self.forget().get("ok"))
        original_authority = self.authority()
        marker = self.vault / ".knowledgeos-vault.json"
        self.retain(marker, "vault-marker.original")
        marker.write_text(json.dumps({"vault_id": secrets.token_hex(16)}), encoding="utf-8")
        self.retain(self.mirror, "changed-marker-mirror.json")
        self.assert_closed(MemoryAPI(self.vault).get_note("Projects/old.md"))
        self.assertEqual(original_authority, self.authority())

    def test_signed_policy_for_another_vault_cannot_be_transplanted(self):
        self.assertTrue(self.forget().get("ok"))
        first = self.authority()
        other = self.root / "other-vault"
        (other / "People").mkdir(parents=True)
        (other / "People/Self.md").write_bytes(self.identity_before)
        (other / "Projects").mkdir()
        (other / "Projects/old.md").write_bytes(self.sources["old"])
        (other / ".knowledgeos-vault.json").write_text(json.dumps({"vault_id": secrets.token_hex(16)}), encoding="utf-8")
        other_api = MemoryAPI(other)
        self.assertTrue(other_api.forget("Projects/old.md", self.sha("old")).get("ok"))
        second = next(path for path in (self.root / "state/vaults").glob("*/remembering-policy.json") if path != first)
        self.retain(second, "other-vault-authority.original")
        second.write_bytes(first.read_bytes())
        self.assert_closed(other_api.get_note("Projects/old.md"))

    def test_tampered_signed_authority_fails_closed_and_preserves_evidence(self):
        self.assertTrue(self.forget().get("ok"))
        authority = self.authority()
        self.retain(authority, "valid-authority.json")
        payload = json.loads(self.mirror.read_bytes())
        payload["state"]["forgotten"] = {}
        altered = json.dumps(payload).encode("utf-8")
        authority.write_bytes(altered)
        self.assert_closed(MemoryAPI(self.vault).get_note("Projects/old.md"))
        self.assertEqual(altered, authority.read_bytes())

    def test_duplicate_fields_in_signed_authority_fail_closed(self):
        self.assertTrue(self.forget().get("ok"))
        authority = self.authority()
        original = authority.read_bytes()
        self.retain(authority, "duplicate-predecessor.json")
        altered = original[:-1] + b',"state":{"version":1,"forgotten":{},"superseded":{}}}'
        authority.write_bytes(altered)
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertEqual(altered, authority.read_bytes())

    def test_missing_or_malformed_signing_key_is_never_rotated(self):
        self.assertTrue(self.forget().get("ok"))
        key = self.root / "state/gate.key"
        self.retain(key, "gate-key.original")
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertFalse(key.exists())
        malformed = b"invalid"
        key.write_bytes(malformed)
        self.assert_closed(self.forget())
        self.assertEqual(malformed, key.read_bytes())

    def test_hardlinked_trusted_authority_and_key_are_refused(self):
        self.assertTrue(self.forget().get("ok"))
        authority = self.authority()
        retained = self.retain(authority, "hardlink-authority.original")
        authority.hardlink_to(retained)
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertEqual(retained.read_bytes(), authority.read_bytes())
        self.retain(authority, "hardlink-authority.link")
        authority.write_bytes(retained.read_bytes())
        key = self.root / "state/gate.key"
        retained_key = self.retain(key, "hardlink-key.original")
        key.hardlink_to(retained_key)
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertEqual(retained_key.read_bytes(), key.read_bytes())

    def test_linked_trusted_parent_is_refused_without_following_it(self):
        self.assertTrue(self.forget().get("ok"))
        parent = self.authority().parent
        held = self.root / "retained/authority-directory"
        held.parent.mkdir(exist_ok=True)
        parent.rename(held)
        before = {p.name: p.read_bytes() for p in held.iterdir() if p.is_file()}
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(held), str(parent))
        else:
            parent.symlink_to(held, target_is_directory=True)
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertEqual(before, {p.name: p.read_bytes() for p in held.iterdir() if p.is_file()})

    def test_trusted_state_cannot_be_redirected_inside_vault(self):
        with mock.patch.dict(os.environ, {"KNOWLEDGEOS_STATE_DIR": str(self.vault / "hidden-state")}):
            self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertFalse((self.vault / "hidden-state").exists())

    def test_legacy_policy_is_adopted_in_full_before_any_release(self):
        self.mirror.parent.mkdir()
        legacy = {"version": 1, "forgotten": {"Projects/other.md": {
                    "sha256": self.sha("other"), "recorded_at": "2026-10-19T00:00:00+00:00", "fingerprints": []}},
                  "superseded": {"Projects/old.md": {
                    "sha256": self.sha("old"), "recorded_at": "2026-10-19T00:00:00+00:00",
                    "replacement": "Projects/current.md", "replacement_sha256": self.sha("current")}}}
        self.mirror.write_text(json.dumps(legacy), encoding="utf-8")
        self.assert_closed(self.api.get_note("Projects/other.md"))
        self.assertEqual(self.api.get_note("Projects/old.md").get("memory_status"), "historical")
        self.assertEqual(json.loads(self.authority().read_bytes())["state"], legacy)
        self.assertEqual(self.mirror.read_bytes(), self.authority().read_bytes())

    def test_failed_authority_publication_preserves_existing_decisions_and_retries(self):
        self.assertTrue(self.forget().get("ok"))
        before = self.mirror.read_bytes()
        with mock.patch("knowledgeos.remembering.atomic_write_bytes", side_effect=OSError("synthetic authority failure")):
            self.assert_closed(self.forget("other"))
        self.assertEqual(before, self.mirror.read_bytes())
        self.assertEqual(before, self.authority().read_bytes())
        self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertIn("Birch", self.api.get_note("Projects/other.md")["body"])
        self.assertTrue(self.forget("other").get("ok"))

    def test_failed_mirror_publication_keeps_committed_restrictions_and_retry_converges(self):
        self.assertTrue(self.forget().get("ok"))
        before = self.mirror.read_bytes()

        def fail_mirror(path, body):
            if Path(path) == self.mirror:
                raise OSError("synthetic second-publication failure")
            return atomic_write_bytes(path, body)

        with mock.patch("knowledgeos.remembering.atomic_write_bytes", side_effect=fail_mirror):
            self.assert_closed(self.forget("other"))
        self.assertEqual(before, self.mirror.read_bytes())
        self.assert_closed(MemoryAPI(self.vault).get_note("Projects/other.md"))
        self.assertTrue(self.forget("other").get("ok"))
        self.assertEqual(self.mirror.read_bytes(), self.authority().read_bytes())

    def test_first_mirror_publication_failure_keeps_authority_and_retry_converges(self):
        def fail_mirror(path, body):
            if Path(path) == self.mirror:
                raise OSError("synthetic initial mirror failure")
            return atomic_write_bytes(path, body)

        with mock.patch("knowledgeos.remembering.atomic_write_bytes", side_effect=fail_mirror):
            self.assert_closed(self.forget())
        self.assertFalse(self.mirror.exists())
        self.assert_closed(MemoryAPI(self.vault).get_note("Projects/old.md"))
        self.assertTrue(self.forget().get("ok"))
        self.assertEqual(self.mirror.read_bytes(), self.authority().read_bytes())

    def test_concurrent_forgetting_and_correction_merge_under_the_same_authority(self):
        jobs = [lambda: self.forget("other"),
                lambda: self.api.supersede("Projects/old.md", self.sha("old"), "Projects/current.md", self.sha("current"))]
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda job: job(), jobs))
        self.assertTrue(all(result.get("ok") for result in results), results)
        self.assert_closed(self.api.get_note("Projects/other.md"))
        self.assertEqual(self.api.get_note("Projects/old.md").get("memory_status"), "historical")

    def test_reviewed_hash_and_identity_protection_still_apply(self):
        self.assert_closed(self.api.forget("Projects/old.md", "0" * 64))
        self.assertFalse(self.mirror.exists())
        self.assert_closed(self.api.forget("People/Self.md", hashlib.sha256(self.identity_before).hexdigest()))
        self.assert_closed(self.api.supersede("People/Self.md", hashlib.sha256(self.identity_before).hexdigest(),
                                             "Projects/current.md", self.sha("current")))
        self.assertTrue(self.forget().get("ok"))

    def test_source_swapped_between_check_and_open_is_not_released(self):
        source = self.vault / "Projects/old.md"
        original_open = os.open
        swapped = False

        def replace_then_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if Path(path) == source and not swapped:
                swapped = True
                source.rename(self.root / "retained-source.md")
                source.write_bytes(b"# Unexpected content\n\nDo not release swapped bytes.\n")
            return original_open(path, flags, *args, **kwargs)

        with mock.patch("knowledgeos.remembering.os.open", side_effect=replace_then_open):
            self.assert_closed(self.api.get_note("Projects/old.md"))
        self.assertTrue(swapped)
        source.write_bytes(self.sources["old"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "native Windows has no POSIX FIFO creation")
    def test_fifo_source_is_refused_before_open(self):
        from knowledgeos.remembering import RememberingPolicy, PolicyError

        source = self.vault / "Projects/fifo.md"
        os.mkfifo(source)
        self.assertIsNone(RememberingPolicy(self.vault).read(source))
        with self.assertRaises(PolicyError):
            RememberingPolicy(self.vault).forget(source, "0" * 64)
        self.assert_closed(self.api.get_note("Projects/fifo.md"))
        self.assert_closed(self.api.forget("Projects/fifo.md", "0" * 64))


if __name__ == "__main__":
    unittest.main()
