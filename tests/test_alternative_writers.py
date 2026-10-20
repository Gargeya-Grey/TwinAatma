"""Public legacy writers cannot overwrite identity or existing user bytes."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
STAGED = os.environ.get("TWIN_WRITER_PRODUCT_ROOT")
PRODUCTS = ("knowledgeos/init_vault.py", "scripts/draft_weekly_synthesis.py", "scripts/onboarding.py")
BASE = ROOT / "work/gc-artifacts/.knowledgeos/alternative-writers-20261019/tests"


def sentinels():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            if (ROOT / name).is_file() else None
            for name in ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json")}


class AlternativeWriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_before = sentinels()
        cls.evidence_dir = BASE / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        cls.evidence_dir.mkdir(parents=True)
        cls.processes = []

    @classmethod
    def tearDownClass(cls):
        result = {"root_sentinels_before": cls.real_before, "root_sentinels_after": sentinels(),
                  "selected_staging": STAGED, "processes": cls.processes,
                  "all_started_processes_stopped": all(p["stopped"] for p in cls.processes)}
        (cls.evidence_dir / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        if cls.real_before != result["root_sentinels_after"]:
            raise AssertionError("Selected real-vault sentinel bytes changed")

    def fixture(self):
        label = hashlib.sha256(self._testMethodName.encode()).hexdigest()[:8]
        vault = self.evidence_dir / label / uuid.uuid4().hex[:8] / "vault"
        vault.mkdir(parents=True)
        for folder in ("knowledgeos", "scripts", "Templates", ".cursor/hooks", ".cursor/rules"):
            if (ROOT / folder).is_dir():
                shutil.copytree(ROOT / folder, vault / folder, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "LICENSE", "knowledgeos.config.example.json", ".cursor/hooks.json"):
            if (ROOT / name).is_file():
                (vault / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, vault / name)
        if STAGED:
            for name in PRODUCTS:
                shutil.copyfile(Path(STAGED) / name, vault / name)
        initialized = self.command(vault, ["-m", "knowledgeos", "init", str(vault), "--name", "Synthetic Owner", "--force", "--non-interactive"])
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
        return vault

    def command(self, vault, args, *, answers=""):
        env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(vault.parent / "isolated-gate"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        for name in ("KNOWLEDGEOS_VAULT", "PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        command = [sys.executable, "-B", *args]
        number = len(self.processes)
        stem = self.evidence_dir / ("command-%03d" % number)
        child = subprocess.Popen(command, cwd=vault, env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        timed_out = False
        try:
            stdout, stderr = child.communicate(answers, timeout=90)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            stdout, stderr = child.communicate(timeout=15)
        row = {"argv": command, "cwd": str(vault), "test": self._testMethodName, "pid": child.pid, "exit_code": child.returncode,
               "stopped": child.poll() is not None, "timed_out": timed_out}
        self.processes.append(row)
        stem.with_suffix(".stdout.txt").write_text(stdout, encoding="utf-8")
        stem.with_suffix(".stderr.txt").write_text(stderr, encoding="utf-8")
        stem.with_suffix(".command.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        self.assertFalse(timed_out, stdout + stderr)
        return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)

    def hardlink(self, source, destination):
        try:
            os.link(source, destination)
        except OSError as error:
            self.skipTest("Native hardlink creation is unavailable: " + str(error))

    def symlink(self, source, destination, *, directory=False):
        try:
            destination.symlink_to(source, target_is_directory=directory)
        except OSError as error:
            self.skipTest("Native symbolic link creation is unavailable: " + str(error))

    def weekly(self, vault, code=None):
        return self.command(vault, ["-c", code] if code else ["scripts/draft_weekly_synthesis.py"])

    def output(self, vault):
        return vault / "Research/Synthesis" / (datetime.date.today().isoformat() + "-weekly-draft.md")

    def reinit(self, vault, extra=()):
        return self.command(vault, ["-m", "knowledgeos", "init", str(vault), "--name", "Another Synthetic Owner", "--force", *extra])

    def change_activity(self, vault):
        today = datetime.date.today().isoformat()
        note = vault / "Projects/Observed.md"
        note.write_bytes(("---\ntype: project\ntitle: Changed synthetic activity\n"
                          "description: Independent fixture activity\nschema: knowledgeos-v0.3\nstatus: active\n"
                          f"created: {today}\nupdated: {today}\ntags: [synthetic]\n---\n# Changed\n").encode())
        result = self.command(vault, ["-c", "from knowledgeos.indexer import rebuild_index; rebuild_index('.')"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def replace_fault(self, operation, condition):
        return ("import os\nfrom unittest.mock import patch\noriginal_replace = os.replace\n"
                "def fail(source, destination):\n"
                f"    if {condition}:\n"
                "        raise OSError('injected replacement failure')\n"
                "    return original_replace(source, destination)\n"
                "patch.object(os, 'replace', fail).start()\n" + operation)

    def partial_write_fault(self, operation):
        return ("import os\nfrom unittest.mock import patch\noriginal_fdopen = os.fdopen\n"
                "class BrokenWriter:\n"
                "    def __init__(self, handle): self.handle = handle\n"
                "    def __enter__(self): self.handle.__enter__(); return self\n"
                "    def __exit__(self, *args): return self.handle.__exit__(*args)\n"
                "    def write(self, payload):\n"
                "        self.handle.write(payload[:max(1,len(payload)//2)])\n"
                "        self.handle.flush()\n"
                "        raise OSError('injected partial write failure')\n"
                "def broken(fd, *args, **kwargs):\n"
                "    handle = original_fdopen(fd, *args, **kwargs)\n"
                "    mode = args[0] if args else kwargs.get('mode', 'r')\n"
                "    return BrokenWriter(handle) if 'w' in mode else handle\n"
                "patch.object(os, 'fdopen', broken).start()\n" + operation)

    def test_weekly_draft_refuses_identity_hardlink(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        before = identity.read_bytes()
        self.hardlink(identity, self.output(vault))
        result = self.weekly(vault)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), before)
        self.assertEqual(self.output(vault).read_bytes(), before)

    def test_init_conflict_refuses_identity_hardlink(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        before = identity.read_bytes()
        alias = vault / "People/Self.new.md"
        self.hardlink(identity, alias)
        result = self.command(vault, ["-m", "knowledgeos", "init", str(vault), "--name", "Another Synthetic Owner", "--force"])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), before)
        self.assertEqual(alias.read_bytes(), before)

    def test_legacy_onboarding_refuses_piped_identity_replacement(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        before = identity.read_bytes()
        result = self.command(vault, ["scripts/onboarding.py"], answers="y\nInjected Synthetic Owner\n" + "\n" * 9)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), before)
        self.assertIn("self", (result.stdout + result.stderr).lower())

    def test_init_preserves_existing_conflict_and_mixed_ending_identity(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        identity.write_bytes(identity.read_bytes() + b"\r\nOwner supplied line.\nKeep ending.\r\n")
        beside = vault / "People/Self.new.md"
        preserved = b"My separate conflict draft.\r\nNever replace it.\n"
        beside.write_bytes(preserved)
        before = identity.read_bytes()
        result = self.reinit(vault)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), before)
        self.assertEqual(beside.read_bytes(), preserved)
        self.assertIn("conflict", result.stderr.lower())

    def test_init_first_conflict_is_complete_and_repeat_is_idempotent(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        before = identity.read_bytes()
        first = self.reinit(vault)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        beside = vault / "People/Self.new.md"
        proposed = beside.read_bytes()
        self.assertIn(b"title: Self (Another Synthetic Owner)", proposed)
        self.assertIn(b"Unknown. No owner-confirmed values", proposed)
        repeated = self.reinit(vault)
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(beside.read_bytes(), proposed)
        self.assertEqual(identity.read_bytes(), before)

    def test_init_refresh_preserves_equivalent_mixed_endings_without_conflict(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        lines = identity.read_bytes().splitlines()
        mixed = b"".join(line + (b"\r\n" if index % 2 else b"\n")
                         for index, line in enumerate(lines))
        identity.write_bytes(mixed)
        result = self.command(vault, ["-m", "knowledgeos", "init", str(vault), "--name", "Synthetic Owner"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), mixed)
        self.assertFalse((vault / "People/Self.new.md").exists(), "Equivalent text needs no conflict draft")

    def test_init_copy_refuses_preexisting_user_conflict(self):
        vault = self.fixture()
        source_name = sorted((vault / "Templates").glob("*.md"))[0].name
        target = vault / "Templates" / source_name
        target.write_bytes(b"My existing template.\r\n")
        beside = target.with_name(target.stem + ".new" + target.suffix)
        beside.write_bytes(b"My user conflict.\n")
        source = self.evidence_dir / ("source-" + uuid.uuid4().hex[:8])
        shutil.copytree(vault / "Templates", source / "Templates")
        (source / "Templates" / source_name).write_bytes(b"New toolkit template.\n")
        code = ("from pathlib import Path\nfrom knowledgeos.init_vault import init_vault\n"
                f"init_vault(Path('.'), source_root=Path({str(source)!r}), force=True)\n")
        result = self.command(vault, ["-c", code])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), b"My existing template.\r\n")
        self.assertEqual(beside.read_bytes(), b"My user conflict.\n")

    def test_init_copy_refuses_hardlinked_conflict(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        before = identity.read_bytes()
        target = vault / "LICENSE"
        target.write_bytes(b"My existing license.\r\n")
        beside = vault / "LICENSE.new"
        self.hardlink(identity, beside)
        source = self.evidence_dir / ("source-" + uuid.uuid4().hex[:8])
        source.mkdir()
        (source / "LICENSE").write_bytes(b"New toolkit license.\n")
        code = ("from pathlib import Path\nfrom knowledgeos.init_vault import init_vault\n"
                f"init_vault(Path('.'), source_root=Path({str(source)!r}), force=True)\n")
        result = self.command(vault, ["-c", code])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), before)
        self.assertEqual(beside.read_bytes(), before)
        self.assertEqual(target.read_bytes(), b"My existing license.\r\n")

    def test_init_refuses_linked_personal_and_template_directories(self):
        for name in ("People", "Templates"):
            with self.subTest(directory=name):
                vault = self.fixture()
                original = vault / name
                retained = vault / ("retained-" + name)
                original.rename(retained)
                self.symlink(retained, original, directory=True)
                before = {p.relative_to(retained).as_posix(): p.read_bytes()
                          for p in retained.rglob("*") if p.is_file()}
                result = self.reinit(vault)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual({p.relative_to(retained).as_posix(): p.read_bytes()
                                  for p in retained.rglob("*") if p.is_file()}, before)

    def test_weekly_refuses_linked_output_and_parent(self):
        for parent in (False, True):
            with self.subTest(parent=parent):
                vault = self.fixture()
                identity = vault / "People/Self.md"
                before = identity.read_bytes()
                if parent:
                    target = vault.parent / "retained-output"
                    target.mkdir()
                    (target / self.output(vault).name).write_bytes(b"Outside original.\r\n")
                    self.output(vault).parent.rename(vault / "Research/retained-synthesis")
                    self.symlink(target, self.output(vault).parent, directory=True)
                    expected = b"Outside original.\r\n"
                else:
                    self.symlink(identity, self.output(vault))
                    expected = before
                result = self.weekly(vault)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(identity.read_bytes(), before)
                self.assertEqual(self.output(vault).read_bytes(), expected)

    def test_init_state_replace_failure_preserves_marker_and_identity(self):
        vault = self.fixture()
        marker = vault / ".knowledgeos-vault.json"
        content = json.loads(marker.read_text(encoding="utf-8"))
        content["toolkit_min_version"] = "0.0.0"
        marker.write_bytes(json.dumps(content).encode())
        before_marker = marker.read_bytes()
        identity = (vault / "People/Self.md").read_bytes()
        operation = "import sys\nfrom knowledgeos.__main__ import main\nsys.exit(main(['init', '.', '--force', '--name', 'Synthetic Owner']))"
        result = self.command(vault, ["-c", self.replace_fault(operation, "str(destination).endswith('.knowledgeos-vault.json')")])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("injected replacement failure", result.stderr)
        self.assertEqual(marker.read_bytes(), before_marker)
        self.assertEqual((vault / "People/Self.md").read_bytes(), identity)
        retry = self.command(vault, ["-m", "knowledgeos", "init", str(vault), "--name", "Synthetic Owner", "--force"])
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertNotEqual(marker.read_bytes(), before_marker)

    def test_init_partial_write_publishes_no_conflict_and_retries(self):
        vault = self.fixture()
        identity = (vault / "People/Self.md").read_bytes()
        operation = "import sys\nfrom knowledgeos.__main__ import main\nsys.exit(main(['init', '.', '--force', '--name', 'Another Synthetic Owner']))"
        result = self.command(vault, ["-c", self.partial_write_fault(operation)])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("injected partial write failure", result.stderr)
        self.assertFalse((vault / "People/Self.new.md").exists())
        self.assertEqual((vault / "People/Self.md").read_bytes(), identity)
        retry = self.reinit(vault)
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertIn(b"Another Synthetic Owner", (vault / "People/Self.new.md").read_bytes())

    def test_init_dry_run_and_force_preserve_personal_bytes(self):
        vault = self.fixture()
        identity = (vault / "People/Self.md").read_bytes()
        before = {p.relative_to(vault).as_posix(): p.read_bytes() for p in vault.rglob("*") if p.is_file()}
        dry = self.reinit(vault, ["--dry-run"])
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertEqual({p.relative_to(vault).as_posix(): p.read_bytes() for p in vault.rglob("*") if p.is_file()}, before)
        absent = vault / "Concepts/_Index.md"
        absent.rename(vault / "Concepts/retained-index.bin")
        filled = self.reinit(vault)
        self.assertEqual(filled.returncode, 0, filled.stdout + filled.stderr)
        self.assertTrue(absent.is_file())
        self.assertEqual((vault / "People/Self.md").read_bytes(), identity)

    def test_weekly_refuses_unowned_and_user_edited_reports(self):
        for owned in (False, True):
            with self.subTest(owned=owned):
                vault = self.fixture()
                if owned:
                    initial = self.weekly(vault)
                    self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
                report = self.output(vault)
                personal = b"My retained weekly draft.\r\nMixed ending.\n"
                report.write_bytes(personal)
                result = self.weekly(vault)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(report.read_bytes(), personal)

    def test_weekly_receipt_and_report_faults_preserve_and_retry(self):
        operation = "import runpy\nrunpy.run_path('scripts/draft_weekly_synthesis.py', run_name='__main__')"
        for fault in ("receipt", "report"):
            with self.subTest(fault=fault):
                vault = self.fixture()
                initial = self.weekly(vault)
                self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
                report = self.output(vault)
                before = report.read_bytes()
                identity = (vault / "People/Self.md").read_bytes()
                self.change_activity(vault)
                condition = ("'.knowledgeos/generated' in str(destination).replace(chr(92), '/')" if fault == "receipt"
                             else "str(destination).endswith('-weekly-draft.md')")
                failed = self.weekly(vault, self.replace_fault(operation, condition))
                self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
                self.assertIn("injected replacement failure", failed.stderr)
                self.assertEqual(report.read_bytes(), before)
                retry = self.weekly(vault)
                self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
                changed = report.read_bytes()
                self.assertNotEqual(changed, before)
                self.assertIn(b"Changed synthetic activity", changed)
                repeated = self.weekly(vault)
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual(report.read_bytes(), changed)
                self.assertEqual((vault / "People/Self.md").read_bytes(), identity)

    def test_weekly_partial_write_preserves_report_and_retries(self):
        vault = self.fixture()
        initial = self.weekly(vault)
        self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
        report = self.output(vault)
        before = report.read_bytes()
        self.change_activity(vault)
        operation = "import runpy\nrunpy.run_path('scripts/draft_weekly_synthesis.py', run_name='__main__')"
        failed = self.weekly(vault, self.partial_write_fault(operation))
        self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        self.assertIn("injected partial write failure", failed.stderr)
        self.assertEqual(report.read_bytes(), before)
        retry = self.weekly(vault)
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertIn(b"Changed synthetic activity", report.read_bytes())

    def test_legacy_onboarding_cannot_create_identity_from_defaults(self):
        vault = self.fixture()
        identity = vault / "People/Self.md"
        identity.rename(vault / "People/retained-identity.bin")
        result = self.command(vault, ["scripts/onboarding.py"], answers="Injected Synthetic Owner\n" + "\n" * 9)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(identity.exists())


if __name__ == "__main__":
    unittest.main()
