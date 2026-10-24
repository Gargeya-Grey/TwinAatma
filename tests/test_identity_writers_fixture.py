"""Writer observations require their real public operations to reach the expected exit."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))
from data_preservation import sha, source_files
from identity_writers import WritersRun

BASE = ROOT / "work/gc-artifacts/.knowledgeos/writer-proof-20261023/fixture-repair"
UNRELATED_SERVER = {"command": "synthetic-unrelated-server", "args": ["keep-this"]}
UNRELATED_SETTING = {"synthetic-owner-setting": "retain this value"}


class ObservedFaultRun(WritersRun):
    def prepare_writer(self, label, **options):
        fixture = super().prepare_writer(label, **options)
        if label == "setup-fault":
            target = fixture["vault"] / ".cursor/mcp.json"
            document = json.loads(target.read_text(encoding="utf-8"))
            self.expected_server = document["mcpServers"]["knowledgeos"]
            document["mcpServers"]["unrelated"] = UNRELATED_SERVER
            document["ownerSetting"] = UNRELATED_SETTING
            target.write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))
        return fixture


class IdentityWriterFaultFixtureTests(unittest.TestCase):
    def new_run(self):
        directory = BASE / "controls" / uuid.uuid4().hex[:8]
        directory.mkdir(parents=True, exist_ok=False)
        revision = subprocess.run(["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
                                  cwd=ROOT, check=True, capture_output=True, text=True, timeout=20)
        freeze = directory / "freeze.json"
        freeze.write_text(json.dumps({"revision": revision.stdout.strip(),
            "product": {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}}, indent=2), encoding="utf-8")
        return ObservedFaultRun(directory / "journey", freeze)

    def record_shutdown(self, run):
        observed = {"scope": "Bounded fault-fixture regression, not complete outcome evidence",
                    "processes": run.processes, "cases": run.checks,
                    "all_started_processes_stopped": bool(run.processes) and all(row["stopped"] for row in run.processes),
                    "real_sentinels_unchanged": run.before == run.sentinels()}
        run.save("regression-observation.json", observed)
        self.assertTrue(observed["all_started_processes_stopped"])
        self.assertTrue(observed["real_sentinels_unchanged"])

    def test_fault_journey_interrupts_setup_then_retries_without_losing_config(self):
        run = self.new_run()
        try:
            run.faults()
            fixture = next(row for row in run.fixtures if row["label"] == "setup-fault")
            target = fixture["vault"] / ".cursor/mcp.json"
            record = json.loads((run.directory / "setup-fault.command.json").read_text(encoding="utf-8"))
            stderr = (run.directory / "setup-fault.stderr.txt").read_text(encoding="utf-8")
            self.assertNotEqual(record["exit_code"], 0, "The setup fault must reach a real write")
            self.assertIn("IDENTITY_WRITER_FAULT=" + str(target), stderr.splitlines())
            before = json.loads((run.directory / "setup-fault.before.json").read_text(encoding="utf-8"))
            after = json.loads((run.directory / "setup-fault.after.json").read_text(encoding="utf-8"))
            self.assertEqual(before["vault/.cursor/mcp.json"], after["vault/.cursor/mcp.json"])
            self.assertEqual(before["vault/People/Self.md"], after["vault/People/Self.md"])
            retry = json.loads((run.directory / "setup-fault-retry.command.json").read_text(encoding="utf-8"))
            self.assertEqual(retry["exit_code"], 0)
            document = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(document["mcpServers"]["knowledgeos"], run.expected_server)
            self.assertEqual(document["mcpServers"]["unrelated"], UNRELATED_SERVER)
            self.assertEqual(document["ownerSetting"], UNRELATED_SETTING)
            self.assertNotEqual(before["vault/.cursor/mcp.json"]["sha256"], sha(target))
            self.assertEqual(before["vault/People/Self.md"]["sha256"], sha(fixture["vault"] / "People/Self.md"))
        finally:
            self.record_shutdown(run)

    def test_unreached_injected_fault_aborts_before_printing_pass(self):
        run = self.new_run()
        try:
            fixture = run.prepare_writer("unreached")
            for name, host, target in (("no-op", "cursor", ".cursor/not-written.json"),
                                       ("refused", "unsupported", ".cursor/mcp.json")):
                arguments = ["setup-host", "--host", host, "--vault", str(fixture["vault"]), "--write"]
                with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "Injected writer fault was not reached"):
                    run.cli_case(name, fixture, arguments, kind="fault", fault=target)
                self.assertFalse(any(row["id"] == "writers." + name for row in run.checks))
        finally:
            self.record_shutdown(run)

    def test_failed_public_script_aborts_before_printing_pass(self):
        run = self.new_run()
        output = io.StringIO()
        try:
            fixture = run.prepare_writer("failed-script")
            name = "unsupported-script-option"
            caught = None
            with contextlib.redirect_stdout(output):
                try:
                    run.script_case(name, fixture, "scripts/intelligence_brief.py",
                                    ["--vault", str(fixture["vault"]), "--unsupported-writer-proof-flag"])
                except RuntimeError as error:
                    caught = error
            record = json.loads((run.directory / (name + ".command.json")).read_text(encoding="utf-8"))
            stderr = (run.directory / (name + ".stderr.txt")).read_text(encoding="utf-8")
            self.assertEqual(record["exit_code"], 2)
            self.assertIn("unrecognized arguments: --unsupported-writer-proof-flag", stderr)
            self.assertTrue((run.directory / (name + ".before.json")).is_file())
            self.assertTrue((run.directory / (name + ".after.json")).is_file())
            self.assertIsInstance(caught, RuntimeError, "A failed public script must not earn a preservation PASS")
            self.assertIn("Public script returned unexpected exit status", str(caught))
            self.assertFalse(any(row["id"] == "writers." + name for row in run.checks))
            self.assertNotIn("PASS writers." + name, output.getvalue())
        finally:
            run.save("script-guard-output.json", {"stdout": output.getvalue()})
            self.record_shutdown(run)

    def test_zero_exit_with_real_fault_marker_aborts_before_printing_pass(self):
        run = self.new_run()
        output = io.StringIO()
        try:
            fixture = run.prepare_writer("degraded-prewarm")
            name = "prewarm-manifest-fault"
            target = fixture["vault"] / ".knowledgeos/index-manifest.json"
            caught = None
            with contextlib.redirect_stdout(output):
                try:
                    run.cli_case(name, fixture, ["breathe", "--vault", str(fixture["vault"]), "--prewarm"],
                                 kind="fault", fault=".knowledgeos/index-manifest.json")
                except RuntimeError as error:
                    caught = error
            record = json.loads((run.directory / (name + ".command.json")).read_text(encoding="utf-8"))
            stderr = (run.directory / (name + ".stderr.txt")).read_text(encoding="utf-8")
            payload = json.loads((run.directory / (name + ".stdout.txt")).read_text(encoding="utf-8"))
            self.assertEqual(record["exit_code"], 0)
            self.assertIn("IDENTITY_WRITER_FAULT=" + str(target), stderr.splitlines())
            self.assertEqual(payload["mode"], "prewarm")
            self.assertIn("injected identity writer replace failure", payload["freshness"]["error"])
            self.assertFalse(payload["freshness"]["rebuilt"])
            self.assertNotEqual(payload["freshness"]["reason"], "fresh")
            self.assertIsInstance(caught, RuntimeError, "An actual marker alone cannot establish an interrupted command")
            self.assertIn("Injected writer fault was not reached", str(caught))
            self.assertFalse(any(row["id"] == "writers." + name for row in run.checks))
            self.assertNotIn("PASS writers." + name, output.getvalue())
        finally:
            run.save("zero-exit-guard-output.json", {"stdout": output.getvalue()})
            self.record_shutdown(run)

    def test_successful_script_and_retired_onboarding_keep_their_expected_status(self):
        run = self.new_run()
        try:
            fixture = run.prepare_writer("script-statuses")
            record, stdout, stderr = run.script_case("script-rebuild_index-0", fixture, "scripts/rebuild_index.py",
                                                    ["--vault", str(fixture["vault"])])
            self.assertEqual(record["exit_code"], 0)
            self.assertIn("Done.", stdout)
            self.assertEqual(run.checks[-1]["verdict"], "PASS")
            record, stdout, stderr = run.script_case("script-onboarding-0", fixture, "scripts/onboarding.py")
            self.assertEqual(record["exit_code"], 1)
            self.assertIn("Legacy onboarding cannot change People/Self.md.", stderr)
            self.assertEqual(run.checks[-1]["verdict"], "PASS")
        finally:
            self.record_shutdown(run)


if __name__ == "__main__":
    unittest.main()
