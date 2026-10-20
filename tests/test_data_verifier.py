"""Export verification needs actual bundle bytes and complete preservation evidence."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

from support import ROOT

SCRIPT = ROOT / ".agents/skills/verify-twinaatma/scripts/data_preservation.py"
spec = importlib.util.spec_from_file_location("data_preservation_proof", SCRIPT)
data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data)


class DataVerifierTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / "work/gc-artifacts/.knowledgeos/data-preservation-20261019/export-worker/tests" / uuid.uuid4().hex
        self.directory.mkdir(parents=True)

    def bundle(self):
        vault = self.directory / "vault"
        output = vault / "bundle"
        output.mkdir(parents=True)
        for relative in data.SELECTION:
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data.NOTES[relative])
        manifest = {"format": "KnowledgeOS portable markdown bundle", "schema": "knowledgeos-v0.2",
                    "created_at": "2026-10-19T00:00:00+00:00", "source_vault": str(vault),
                    "selector": {"project": None, "paths": data.SELECTION},
                    "notes": data.EXPECTED_ENTRIES, "dependency_policy": data.DEPENDENCY_POLICY,
                    "remembering_policy": "Excluded notes are omitted. Historical sources retain explicit attribution in this manifest.",
                    "excluded_count": 0}
        (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return vault, output, manifest

    def test_printed_success_and_selected_files_without_manifest_do_not_prove_export(self):
        vault, output, _ = self.bundle()
        (output / "manifest.json").unlink()
        observed = data.bundle_observation(vault, "bundle")
        self.assertEqual(observed["manifest_present"], False)
        self.assertEqual(observed["valid"], False)

    def test_manifest_must_match_literal_entries_and_dependency_omissions(self):
        vault, output, manifest = self.bundle()
        self.assertEqual(data.bundle_observation(vault, "bundle")["valid"], True)
        for field, value in (("notes", []), ("dependency_policy", "All dependencies included"),
                             ("source_vault", "unrelated"), ("selector", {"paths": []})):
            changed = dict(manifest, **{field: value})
            (output / "manifest.json").write_text(json.dumps(changed), encoding="utf-8")
            with self.subTest(field=field):
                self.assertEqual(data.bundle_observation(vault, "bundle")["valid"], False)

    def test_selected_byte_drift_and_unselected_content_are_detected(self):
        vault, output, _ = self.bundle()
        target = output / data.SELECTION[0]
        target.write_bytes(b"Changed source bytes\n")
        self.assertEqual(data.bundle_observation(vault, "bundle")["valid"], False)
        target.write_bytes(data.NOTES[data.SELECTION[0]])
        (output / "Research").mkdir()
        (output / "Research/Context.md").write_bytes(data.NOTES["Research/Context.md"])
        self.assertEqual(data.bundle_observation(vault, "bundle")["valid"], False)

    def test_preservation_checks_removed_changed_and_new_entries_outside_owned_bundle(self):
        before = {"vault/People/Self.md": {"sha256": "original"}, "outside/sentinel.bin": {"sha256": "private"}}
        self.assertEqual(data.preservation_observation(before, dict(before, **{"vault/bundle/new.md": {"sha256": "export"}}), "bundle")["unchanged"], True)
        for changed in ({}, dict(before, **{"vault/People/Self.md": {"sha256": "edited"}}),
                        dict(before, **{"outside/new.md": {"sha256": "new"}}),
                        dict(before, **{"vault/bundle-prefix/personal.md": {"sha256": "new"}})):
            with self.subTest(changed=changed):
                self.assertEqual(data.preservation_observation(before, changed, "bundle")["unchanged"], False)

    def test_inventory_records_links_without_traversing_external_targets(self):
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "private.md").write_bytes(b"Retain\n")
        scope = self.directory / "scope"
        scope.mkdir()
        try:
            (scope / "linked").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        observed = data.inventory(scope)
        self.assertEqual(observed, {"linked": {"kind": "link", "target": os.readlink(scope / "linked")}})

    def test_actual_export_cli_produces_exact_bundle_and_preserves_complete_source(self):
        run = data.DataRun(self.directory)
        run.export(("fresh_bundle", data.SELECTION, "bundle-fresh", "bundle"))
        self.assertEqual(run.cases[0]["verdict"], "PASS", run.cases)
        self.assertEqual(run.processes[0]["stopped"], True)
        command = json.loads((run.directory / "fresh_bundle.command.json").read_text(encoding="utf-8"))
        self.assertEqual(command["command"][0:2], [sys.executable, "-B"])
        self.assertEqual(command["shell"], False)
        self.assertEqual(command["exit_code"], 0)
        self.assertEqual(command["vault"], command["cwd"])

    def test_success_shaped_export_cli_without_bundle_fails_the_public_journey(self):
        run = data.DataRun(self.directory)
        actual_fixture = run.fixture
        def false_success(identifier):
            scope, vault, outside = actual_fixture(identifier)
            (vault / "scripts/export_bundle.py").write_text("print('Exported 2 notes. Manifest created.')\n", encoding="utf-8")
            return scope, vault, outside
        run.fixture = false_success
        run.export(("fresh_bundle", data.SELECTION, "bundle-fresh", "bundle"))
        self.assertEqual(run.cases[0]["observed"]["exit_code"], 0)
        self.assertEqual(run.cases[0]["verdict"], "FAIL")
        self.assertEqual(run.cases[0]["observed"]["bundle"]["manifest_present"], False)

    def test_refusal_with_source_damage_is_failed_even_with_error_diagnostics(self):
        run = data.DataRun(self.directory)
        actual_fixture = run.fixture
        def damaged_refusal(identifier):
            scope, vault, outside = actual_fixture(identifier)
            (vault / "scripts/export_bundle.py").write_text(
                "from pathlib import Path\nimport sys\nPath('People/Self.md').write_bytes(b'damaged')\nprint('Refused output', file=sys.stderr)\nraise SystemExit(1)\n", encoding="utf-8")
            return scope, vault, outside
        run.fixture = damaged_refusal
        run.export(("existing_directory", ["Concepts"], "unowned", "refuse"))
        self.assertEqual(run.cases[0]["verdict"], "FAIL")
        self.assertEqual(run.cases[0]["observed"]["protected_bytes_unchanged"], False)
        self.assertEqual(run.cases[0]["observed"]["unchanged"], False)

    def test_output_outside_synthetic_note_exclusion_is_rejected(self):
        with self.assertRaises(ValueError):
            data.DataRun(ROOT / "work/gc-artifacts/uncontained-data-proof")

    def test_timed_out_owned_child_is_reaped_and_evidence_is_retained(self):
        run = data.DataRun(self.directory)
        record, _, _ = run.command("timeout-control", [sys.executable, "-I", "-c", "import time;time.sleep(60)"],
                                   cwd=run.directory, timeout=0.1)
        self.assertEqual(record["error"], "Command exceeded the proof deadline")
        self.assertEqual(record["stopped"], True)
        self.assertNotEqual(record["exit_code"], 0)
        self.assertEqual(run.processes[0]["stopped"], True)
        self.assertTrue((run.directory / "timeout-control.command.json").is_file())

    def test_parent_traversal_cannot_escape_the_excluded_output_subtree(self):
        requested = ROOT / "work/gc-artifacts/.knowledgeos/../../../proof-escape"
        with self.assertRaises(ValueError):
            data.checked_output(requested)
        self.assertEqual((ROOT / "proof-escape").exists(), False)

    @unittest.skipUnless(os.name == "nt", "Windows junction acceptance")
    def test_output_may_not_traverse_a_windows_junction(self):
        target = self.directory / "target"
        target.mkdir()
        junction = self.directory / "junction"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                                capture_output=True, text=True)
        if result.returncode:
            self.skipTest(result.stdout + result.stderr)
        with self.assertRaises(ValueError):
            data.checked_output(junction / "new")


if __name__ == "__main__":
    unittest.main()
