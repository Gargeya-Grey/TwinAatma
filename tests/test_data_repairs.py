"""DATA acceptance checks through copied script CLIs and public report writers."""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DataRepairTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / "work/gc-artifacts/.knowledgeos/repair-20261019/data" / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        (self.vault / "MOCs").mkdir()
        shutil.copytree(ROOT / "knowledgeos", self.vault / "knowledgeos", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "scripts", self.vault / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        self.write("People/Self.md", "# Self\n[[Target]]\n")
        self.write("Concepts/Target.md", "# Target\n")

    def tearDown(self):
        pass  # Retain synthetic copies; they are not real artifact-observer coverage.

    def write(self, relative, text):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        return path

    def cli(self, script, *args):
        return subprocess.run([sys.executable, "-B", str(self.vault / "scripts" / script), *args], cwd=self.vault, capture_output=True, text=True, timeout=60)

    def code(self, code):
        env = os.environ.copy()
        env["KNOWLEDGEOS_STATE_DIR"] = str(self.root / "state")
        return subprocess.run([sys.executable, "-B", "-c", code], cwd=self.vault, env=env, capture_output=True, text=True, timeout=60)

    def index(self):
        result = self.code("from knowledgeos.indexer import rebuild_index; rebuild_index('.')")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def report(self, function):
        return self.code("from knowledgeos.memory import MemoryAPI; from knowledgeos.intelligence import " + function + "; " + function + "(MemoryAPI('.'))")

    def test_export_refuses_existing_identity_and_source_directories(self):
        for output in ("People", "Concepts"):
            before = {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob("*.md")}
            result = self.cli("export_bundle.py", "--paths", "Concepts", "--out", output)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(before, {p.relative_to(self.vault): p.read_bytes() for p in self.vault.rglob("*.md")})

    def test_export_refuses_prefix_sibling_and_nested_source_output(self):
        for output in ("../vault-sibling/bundle", "Concepts/bundle"):
            result = self.cli("export_bundle.py", "--paths", "Concepts", "--out", output)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "vault-sibling").exists())
        self.assertFalse((self.vault / "Concepts/bundle").exists())

    def test_export_fresh_bundle_preserves_source_and_manifest(self):
        result = self.cli("export_bundle.py", "--paths", "Concepts", "--out", "exports/fresh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.vault / "exports/fresh/Concepts/Target.md").read_bytes(), b"# Target\n")
        self.assertTrue((self.vault / "exports/fresh/manifest.json").is_file())

    def test_export_preserves_unowned_output_and_refuses_linked_source(self):
        sentinel = self.write("exports/unowned/personal.txt", "Keep this\n")
        result = self.cli("export_bundle.py", "--paths", "Concepts", "--out", "exports/unowned")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sentinel.read_bytes(), b"Keep this\n")
        external = self.root / "external-notes"
        external.mkdir()
        (external / "private.md").write_bytes(b"Never export me\n")
        self.directory_link(self.vault / "LinkedNotes", external)
        result = self.cli("export_bundle.py", "--paths", "LinkedNotes", "--out", "exports/fresh")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.vault / "exports/fresh").exists())

    def test_link_refactor_preserves_identity_evidence_examples_and_ambiguity(self):
        self.write("knowledge_index.db", "")
        proposal = self.write("People/Self-Proposals/proposal.md", "# Proposal\n[[Target]]\n")
        self.write("Other/Target.md", "# Other target\n")
        note = self.write("Inbox/Example.md", "```md\n[[Concepts/Target]]\n```\n`[[Concepts/Target]]`\n[[Target]]\n[[Concepts/Target|Named]]\n")
        before_self = (self.vault / "People/Self.md").read_bytes()
        before_proposal = proposal.read_bytes()
        result = self.cli("refactor_links.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.vault / "People/Self.md").read_bytes(), before_self)
        self.assertEqual(proposal.read_bytes(), before_proposal)
        self.assertEqual(note.read_bytes(), b"```md\n[[Concepts/Target]]\n```\n`[[Concepts/Target]]`\n[[Target]]\n[Named](../Concepts/Target.md)\n")

    def test_link_refactor_preserves_mixed_endings(self):
        self.write("knowledge_index.db", "")
        note = self.write("Inbox/Edit.md", "Unchanged\r\n[[Concepts/Target]]\nLast\r\n")
        result = self.cli("refactor_links.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(note.read_bytes(), b"Unchanged\r\n[Concepts/Target](../Concepts/Target.md)\r\nLast\r\n")

    def test_reports_preserve_edited_outputs(self):
        self.index()
        for function in ("learning_trajectory_report", "weekly_intelligence_report", "write_intelligence_views"):
            first = self.report(function)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        today = datetime.date.today().isoformat()
        paths = {
            "learning_trajectory_report": f"Research/Synthesis/{today}-learning-trajectory.md",
            "weekly_intelligence_report": f"Research/Synthesis/{today}-intelligence-brief.md",
            "write_intelligence_views": "MOCs/_MOC_Stale_Projects.md",
        }
        for function, rel in paths.items():
            path = self.write(rel, "USER EDIT\n")
            second = self.report(function)
            self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(path.read_bytes(), b"USER EDIT\n")

    def test_report_and_dashboards_refuse_hardlinked_targets(self):
        self.index()
        source = self.vault / "People/Self.md"
        before = source.read_bytes()
        today = datetime.date.today().isoformat()
        targets = [
            (f"Research/Synthesis/{today}-learning-trajectory.md", lambda: self.report("learning_trajectory_report")),
            (f"Research/Synthesis/{today}-intelligence-brief.md", lambda: self.report("weekly_intelligence_report")),
            ("MOCs/_MOC_Stale_Projects.md", lambda: self.report("write_intelligence_views")),
            ("MOCs/_MOC_Experiments.md", lambda: self.cli("experiment_dashboard.py")),
            ("MOCs/_MOC_Outcomes.md", lambda: self.cli("outcomes_dashboard.py")),
        ]
        for rel, run in targets:
            target = self.vault / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
            result = run()
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(source.read_bytes(), before)

    def directory_link(self, link, target):
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_linked_report_parents_and_export_outputs_are_refused(self):
        self.index()
        protected = self.root / "protected"
        protected.mkdir()
        sentinel = protected / "sentinel.md"
        sentinel.write_bytes(b"PRESERVE\n")
        (self.vault / "MOCs").rename(self.vault / "MOCs-original")
        for name in ("MOCs", "Research", "exports"):
            self.directory_link(self.vault / name, protected)
        runs = [
            self.report("learning_trajectory_report"), self.report("weekly_intelligence_report"),
            self.report("write_intelligence_views"), self.cli("experiment_dashboard.py"),
            self.cli("outcomes_dashboard.py"),
            self.cli("export_bundle.py", "--paths", "Concepts", "--out", "exports/fresh"),
        ]
        for result in runs:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in protected.iterdir()), ["sentinel.md"])
        self.assertEqual(sentinel.read_bytes(), b"PRESERVE\n")

    def test_dashboard_preserves_unowned_files(self):
        self.index()
        for script, rel in (("experiment_dashboard.py", "MOCs/_MOC_Experiments.md"), ("outcomes_dashboard.py", "MOCs/_MOC_Outcomes.md")):
            output = self.write(rel, "Unowned personal content\n")
            result = self.cli(script)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output.read_bytes(), b"Unowned personal content\n")

    def test_generated_report_can_regenerate_before_user_edits(self):
        self.index()
        first = self.report("learning_trajectory_report")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.write("Decisions/changed.md", "---\ntype: decision\ntitle: A newly recorded decision\nupdated: 2026-10-19\n---\nA decision.\n")
        self.index()
        second = self.report("learning_trajectory_report")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        output = self.vault / f"Research/Synthesis/{datetime.date.today().isoformat()}-learning-trajectory.md"
        self.assertIn(b"A newly recorded decision", output.read_bytes())

    def test_link_refactor_failed_replace_retains_original_bytes(self):
        self.write("knowledge_index.db", "")
        note = self.write("Inbox/Edit.md", "Keep\r\n[[Concepts/Target]]\n")
        before = note.read_bytes()
        result = self.code("import os, runpy; from unittest.mock import patch; failure = patch.object(os, 'replace', side_effect=OSError('injected replacement failure')); failure.start(); runpy.run_path('scripts/refactor_links.py', run_name='__main__')")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(note.read_bytes(), before)

    def test_hook_install_preserves_existing_hook_and_custom_location(self):
        subprocess.run(["git", "init", "--quiet", str(self.vault)], check=True, capture_output=True)
        hook = self.write(".git/hooks/pre-commit", "#!/bin/sh\necho mine\n")
        result = self.cli("setup_git_hooks.py")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(hook.read_bytes(), b"#!/bin/sh\necho mine\n")
        subprocess.run(["git", "-C", str(self.vault), "config", "core.hooksPath", ".custom-hooks"], check=True, capture_output=True)
        result = self.cli("setup_git_hooks.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.vault / ".custom-hooks/pre-commit").is_file())
        self.assertEqual(hook.read_bytes(), b"#!/bin/sh\necho mine\n")
        installed = (self.vault / ".custom-hooks/pre-commit").read_bytes()
        repeated = self.cli("setup_git_hooks.py")
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual((self.vault / ".custom-hooks/pre-commit").read_bytes(), installed)

    def test_hook_installer_refuses_external_or_linked_custom_location(self):
        subprocess.run(["git", "init", "--quiet", str(self.vault)], check=True, capture_output=True)
        protected = self.root / "external-hooks"
        protected.mkdir()
        for location in (str(protected), ".linked-hooks"):
            if location == ".linked-hooks":
                self.directory_link(self.vault / location, protected)
            subprocess.run(["git", "-C", str(self.vault), "config", "core.hooksPath", location], check=True, capture_output=True)
            result = self.cli("setup_git_hooks.py")
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(protected.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
