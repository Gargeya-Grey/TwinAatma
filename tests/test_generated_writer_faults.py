"""Public report writers preserve prior reports when filesystem commits fail."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
WRITERS = (
    ("trajectory", "from knowledgeos.memory import MemoryAPI; from knowledgeos.intelligence import learning_trajectory_report; learning_trajectory_report(MemoryAPI('.'))"),
    ("weekly", "from knowledgeos.memory import MemoryAPI; from knowledgeos.intelligence import weekly_intelligence_report; weekly_intelligence_report(MemoryAPI('.'))"),
    ("views", "from knowledgeos.memory import MemoryAPI; from knowledgeos.intelligence import write_intelligence_views; write_intelligence_views(MemoryAPI('.'))"),
    ("experiments", "import runpy; runpy.run_path('scripts/experiment_dashboard.py', run_name='__main__')"),
    ("outcomes", "import runpy; runpy.run_path('scripts/outcomes_dashboard.py', run_name='__main__')"),
)


class GeneratedWriterFaultTests(unittest.TestCase):
    def fixture(self, writer):
        vault = ROOT / "work/gc-artifacts/.knowledgeos/data-preservation-20261019/fault-tests" / uuid.uuid4().hex / writer
        vault.mkdir(parents=True)
        for folder in ("knowledgeos", "scripts"):
            shutil.copytree(ROOT / folder, vault / folder, ignore=shutil.ignore_patterns("__pycache__"))
        (vault / "MOCs").mkdir()
        (vault / "People").mkdir()
        (vault / "People/Self.md").write_bytes(b"# Self\nUnknown synthetic identity.\r\n")
        return vault

    def command(self, vault, code):
        env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(vault.parent / "isolated-gate"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        for key in ("KNOWLEDGEOS_VAULT", "PYTHONPATH", "PYTHONHOME"):
            env.pop(key, None)
        return subprocess.run([sys.executable, "-B", "-c", code], cwd=vault, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def index(self, vault):
        result = self.command(vault, "from knowledgeos.indexer import rebuild_index; rebuild_index('.')")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def change_sources(self, vault):
        today = datetime.date.today().isoformat()
        for folder, kind in (("Decisions", "decision"), ("Experiments", "experiment"), ("Projects", "project")):
            path = vault / folder / "Changed.md"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes((f"---\ntype: {kind}\ntitle: Newly recorded {kind}\nstatus: active\n"
                              f"created: {today}\nupdated: 2020-01-01\ntags: [synthetic]\n---\n# Changed\n").encode())
        self.index(vault)

    def snapshot(self, vault):
        return {p.relative_to(vault).as_posix(): p.read_bytes()
                for folder in ("MOCs", "Research", "People", "Decisions", "Experiments", "Projects")
                for p in (vault / folder).rglob("*") if p.is_file()}

    def injected_operation(self, operation, fault):
        condition = "'.knowledgeos/generated' in str(destination).replace(chr(92), '/')" if fault == "receipt" else "str(destination).endswith('.md')"
        return ("import os\nfrom unittest.mock import patch\n"
                "original_replace = os.replace\n"
                "def fail_selected(source, destination):\n"
                f"    if {condition}:\n"
                f"        raise OSError('injected {fault} replacement failure')\n"
                "    return original_replace(source, destination)\n"
                "patch.object(os, 'replace', fail_selected).start()\n" + operation)

    def fault_case(self, writer, operation, fault):
        vault = self.fixture(writer)
        self.index(vault)
        initial = self.command(vault, operation)
        self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
        self.change_sources(vault)
        before = self.snapshot(vault)
        failed = self.command(vault, self.injected_operation(operation, fault))
        self.assertNotEqual(failed.returncode, 0, "Fixture must actually encounter the injected write failure")
        self.assertIn("injected " + fault, failed.stderr)
        self.assertEqual(before, self.snapshot(vault), "A failed commit must retain original report and source bytes")
        retried = self.command(vault, operation)
        self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
        self.assertNotEqual(before, self.snapshot(vault), "Retry must publish the changed source evidence")
        self.assertEqual((vault / "People/Self.md").read_bytes(), b"# Self\nUnknown synthetic identity.\r\n")

    def test_receipt_commit_failure_preserves_original_reports_and_retries(self):
        for writer, operation in WRITERS:
            with self.subTest(writer=writer):
                self.fault_case(writer, operation, "receipt")

    def test_report_commit_failure_preserves_original_reports_and_retries(self):
        for writer, operation in WRITERS:
            with self.subTest(writer=writer):
                self.fault_case(writer, operation, "report")

    def test_legacy_hash_receipts_upgrade_during_regeneration(self):
        for writer, operation in WRITERS:
            with self.subTest(writer=writer):
                vault = self.fixture(writer)
                self.index(vault)
                initial = self.command(vault, operation)
                self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
                receipts = list((vault / ".knowledgeos/generated").glob("*.sha256"))
                self.assertTrue(receipts)
                for receipt in receipts:
                    intent = json.loads(receipt.read_text(encoding="ascii"))
                    receipt.write_bytes(intent["after_sha256"].encode("ascii"))
                self.change_sources(vault)
                before = self.snapshot(vault)
                regenerated = self.command(vault, operation)
                self.assertEqual(regenerated.returncode, 0, regenerated.stdout + regenerated.stderr)
                self.assertNotEqual(before, self.snapshot(vault))
                upgraded = [json.loads(p.read_text(encoding="ascii")) for p in receipts
                            if p.read_bytes().startswith(b"{")]
                self.assertTrue(upgraded, "A changed legacy output must acquire a recoverable write intent")
                for intent in upgraded:
                    self.assertEqual(intent["schema"], "twinaatma.generated-write/v1")
                    self.assertNotEqual(intent["before_sha256"], intent["after_sha256"])
                repeated = self.command(vault, operation)
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)

    def test_interrupted_regeneration_preserves_later_user_edits(self):
        today = datetime.date.today().isoformat()
        targets = {
            "trajectory": f"Research/Synthesis/{today}-learning-trajectory.md",
            "weekly": f"Research/Synthesis/{today}-intelligence-brief.md",
            "views": "MOCs/_MOC_Stale_Projects.md",
            "experiments": "MOCs/_MOC_Experiments.md",
            "outcomes": "MOCs/_MOC_Outcomes.md",
        }
        for writer, operation in WRITERS:
            with self.subTest(writer=writer):
                vault = self.fixture(writer)
                self.index(vault)
                initial = self.command(vault, operation)
                self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
                self.change_sources(vault)
                failed = self.command(vault, self.injected_operation(operation, "report"))
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("injected report", failed.stderr)
                (vault / targets[writer]).write_bytes(b"A human edited this report after the interrupted run.\r\n")
                before = self.snapshot(vault)
                retried = self.command(vault, operation)
                self.assertNotEqual(retried.returncode, 0)
                self.assertIn("Refusing to replace unowned or edited generated output", retried.stderr)
                self.assertEqual(before, self.snapshot(vault))

    def test_invalid_receipts_are_refused_before_any_report_change(self):
        valid = {"schema": "twinaatma.generated-write/v1", "before_sha256": "0" * 64, "after_sha256": "1" * 64}
        invalid = [
            "not a receipt", "0" * 63, "[]",
            json.dumps(dict(valid, schema="twinaatma.generated-write/v2")),
            json.dumps(dict(valid, unexpected=True)),
            json.dumps({"schema": valid["schema"], "after_sha256": "1" * 64}),
            json.dumps(dict(valid, before_sha256=[])),
            json.dumps(dict(valid, after_sha256=None)),
            json.dumps(dict(valid, before_sha256="not a hash")),
        ]
        for writer, operation in WRITERS:
            vault = self.fixture(writer)
            self.index(vault)
            initial = self.command(vault, operation)
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
            receipts = list((vault / ".knowledgeos/generated").glob("*.sha256"))
            self.assertTrue(receipts)
            for bad in invalid:
                with self.subTest(writer=writer, receipt=bad):
                    for receipt in receipts:
                        receipt.write_bytes(bad.encode("ascii"))
                    before = self.snapshot(vault)
                    rejected = self.command(vault, operation)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn("Invalid generated output receipt", rejected.stderr)
                    self.assertEqual(before, self.snapshot(vault))
                    self.assertEqual([p.read_bytes() for p in receipts], [bad.encode("ascii")] * len(receipts))

    def test_initial_creation_failure_retries_without_repair(self):
        for writer, operation in WRITERS:
            for fault in ("receipt", "report"):
                with self.subTest(writer=writer, fault=fault):
                    vault = self.fixture(writer)
                    self.index(vault)
                    before = self.snapshot(vault)
                    failed = self.command(vault, self.injected_operation(operation, fault))
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertIn("injected " + fault, failed.stderr)
                    self.assertEqual(before, self.snapshot(vault))
                    retried = self.command(vault, operation)
                    self.assertEqual(retried.returncode, 0, retried.stdout + retried.stderr)
                    self.assertNotEqual(before, self.snapshot(vault))


if __name__ == "__main__":
    unittest.main()
