import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agents/skills/verify-twinaatma/scripts/acceptance.py'


class AcceptanceScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('acceptance', SCRIPT)
        cls.metric = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.metric)

    def setUp(self):
        base = ROOT / 'work/gc-artifacts/.knowledgeos/installed-host-20261019/scoring-worker/test-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def command(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), *map(str, args)], cwd=ROOT,
                              capture_output=True, text=True, encoding='utf-8', timeout=20)

    def report(self, checks=None):
        checks = checks or ['setup.cli_init', 'setup.doctor']
        transcript = self.directory / 'transcript.jsonl'
        transcript.write_text(json.dumps({'kind': 'mcp', 'requests': [
            {'method': 'initialize'}], 'stdout': '{}', 'exit_code': 0}) + '\n', encoding='utf-8')
        report = {'journey': 'core', 'scope': 'Source CLI/MCP with a synthetic vault; not real-host acceptance',
                  'source_hashes': dict(self.metric.product_hashes(), **{
                      '.agents/skills/verify-twinaatma/scripts/verify.py': self.metric.sha(SCRIPT.with_name('verify.py'))}),
                  'directory': str(self.directory),
                  'checks': [{'id': n, 'verdict': 'PASS', 'observed': {'literal': True}} for n in
                             [*checks, 'evidence.source_unchanged', 'isolation.real_vault_sentinels_unchanged']],
                  'processes': [{'pid': 123, 'stopped': True, 'exit_code': 0}],
                  'all_started_mcp_processes_stopped': True, 'verdict': 'PASS'}
        path = self.directory / 'report.json'
        path.write_text(json.dumps(report), encoding='utf-8')
        return path, report

    def test_empty_snapshot_has_fixed_denominator_and_unknowns_veto(self):
        output = self.directory / 'score.json'
        result = self.command('--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        score = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(score['denominator'], 54)
        self.assertEqual(score['verified_fulfillment_percent'], 0)
        self.assertEqual(score['unresolved_percent'], 100)
        self.assertEqual(score['counts']['NOT CHECKED'], 54)
        self.assertEqual(score['readiness_verdict'], 'NOT ACCEPTED')
        self.assertEqual(len(score['mandatory_vetoes']), 54)

    def test_source_proof_cannot_award_host_or_artifact_outcomes(self):
        report, _ = self.report()
        output = self.directory / 'score.json'
        result = self.command('--source-report', report, '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        score = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(score['counts']['PASS'], 1)
        self.assertEqual(score['outcomes']['SETUP.source_ready']['verdict'], 'PASS')
        self.assertEqual(score['outcomes']['SETUP.host_discovery']['verdict'], 'NOT CHECKED')
        self.assertEqual(score['outcomes']['SETUP.artifact_install']['verdict'], 'NOT CHECKED')

    def test_stale_product_hash_cannot_award_pass(self):
        report, data = self.report()
        data['source_hashes']['knowledgeos/host_setup.py'] = '0' * 64
        report.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--source-report', report, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('product hash', result.stderr)

    def test_assertion_without_observation_is_rejected(self):
        report, data = self.report()
        del data['checks'][0]['observed']
        report.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--source-report', report, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('observed', result.stderr)

    def test_failed_required_assertion_is_fail_not_partial_pass(self):
        report, data = self.report()
        data['checks'][0]['verdict'] = 'FAIL'
        data['verdict'] = 'FAIL'
        report.write_text(json.dumps(data), encoding='utf-8')
        output = self.directory / 'score.json'
        result = self.command('--source-report', report, '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        score = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(score['outcomes']['SETUP.source_ready']['verdict'], 'FAIL')
        self.assertEqual(score['verified_fulfillment_percent'], 0)

    def test_duplicate_assertions_cannot_overwrite_failure(self):
        report, data = self.report()
        data['checks'].append({'id': 'setup.cli_init', 'verdict': 'PASS', 'observed': True})
        report.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--source-report', report, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('duplicate', result.stderr)

    def test_baseline_comparison_reports_fixed_denominator_delta(self):
        before = self.directory / 'before.json'
        self.assertEqual(self.command('--output', before).returncode, 0)
        report, _ = self.report()
        after = self.directory / 'after.json'
        result = self.command('--source-report', report, '--baseline', before, '--output', after)
        self.assertEqual(result.returncode, 0, result.stderr)
        delta = json.loads(after.read_text(encoding='utf-8'))['comparison']
        self.assertEqual(delta['newly_verified'], ['SETUP.source_ready'])
        self.assertEqual(delta['regressed'], [])
        self.assertAlmostEqual(delta['fulfillment_percentage_point_change'], 100 / 54, places=5)

    def test_denominator_change_cannot_improve_score(self):
        before = self.directory / 'before.json'
        self.command('--output', before)
        data = json.loads(before.read_text(encoding='utf-8'))
        data['denominator'] = 1
        before.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--baseline', before, '--output', self.directory / 'after.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('denominator', result.stderr)

    def test_manual_claims_are_not_supported_report_inputs(self):
        path = self.directory / 'manual.json'
        path.write_text(json.dumps({'checks': [{'id': 'host.discovery', 'verdict': 'PASS',
                                               'observed': 'I saw it work'}]}), encoding='utf-8')
        result = self.command('--host-report', path, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('producer', result.stderr)

    def test_missing_transcript_and_unstopped_process_fail_closed(self):
        report, data = self.report()
        (self.directory / 'transcript.jsonl').unlink()
        result = self.command('--source-report', report, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('transcript', result.stderr)
        self.report()
        data['all_started_mcp_processes_stopped'] = False
        report.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--source-report', report, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('process', result.stderr)


    def host_report(self):
        producer = self.directory / 'host.py'
        producer.write_text('# Synthetic report producer fixture, not product evidence.\n', encoding='utf-8')
        transcript = self.directory / 'events.jsonl'
        transcript.write_text('{"type":"fixture"}\n', encoding='utf-8')
        data = {'producer': 'verify-twinaatma.host/v1', 'producer_sha256': self.metric.sha(producer),
                'product_hashes': self.metric.product_hashes(),
                'product_unchanged': True, 'server_source_bound': True,
                'host': {'name': 'synthetic-test-only', 'version': '1', 'mode': 'fixture'},
                'transcript_files': {'events.jsonl': self.metric.sha(transcript)},
                'cases': [{'id': 'host.discovery', 'verdict': 'PASS', 'expected': 'tools visible',
                           'observed': {'tools': ['memory_session_start']}, 'evidence': ['events.jsonl']},
                          {'id': 'host.first_memory_call', 'verdict': 'PASS', 'expected': 'first tool start',
                           'observed': {'first_tool': 'memory_session_start'}, 'evidence': ['events.jsonl']}],
                'processes': [{'pid': 123, 'stopped': True, 'exit_code': 0}],
                'isolation': {'before': {'self': 'fixture'}, 'after': {'self': 'fixture'}}}
        path = self.directory / 'host-report.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return path, data

    def test_host_report_requires_verified_source_binding_and_stable_product(self):
        for field in ('product_unchanged', 'server_source_bound'):
            for value in (None, False, 'true'):
                with self.subTest(field=field, value=value):
                    path, data = self.host_report()
                    data[field] = value
                    path.write_text(json.dumps(data), encoding='utf-8')
                    with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
                        with self.assertRaisesRegex(ValueError, 'source binding|product changed'):
                            self.metric.host_report(path, self.metric.product_hashes())

    def test_deleted_product_module_invalidates_old_evidence(self):
        for field in ('product_hashes', 'source_hashes'):
            with self.subTest(field=field):
                declared = self.metric.product_hashes()
                declared['knowledgeos/deleted_module.py'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'exact current product'):
                    self.metric.check_product({field: declared}, field, self.metric.product_hashes())

    def test_host_adapter_requires_literal_scoped_hashed_observations(self):
        path, data = self.host_report()
        with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
            report = self.metric.host_report(path, self.metric.product_hashes())
        self.assertEqual(report['scope'], 'real_host')
        rubric = self.metric.read_json(self.metric.RUBRIC)
        item = next(i for i in rubric['outcomes'] if i['id'] == 'SETUP.host_discovery')
        self.assertEqual(self.metric.outcome(item, [report])['verdict'], 'PASS')
        data['cases'][1]['verdict'] = 'NOT CHECKED'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
            report = self.metric.host_report(path, self.metric.product_hashes())
        self.assertEqual(self.metric.outcome(item, [report])['verdict'], 'NOT CHECKED')

    def test_host_transcript_tampering_cannot_award_pass(self):
        path, _ = self.host_report()
        (self.directory / 'events.jsonl').write_text('changed', encoding='utf-8')
        with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                self.metric.host_report(path, self.metric.product_hashes())

    def test_host_unknown_pass_claim_and_missing_evidence_are_rejected(self):
        path, data = self.host_report()
        data['cases'][0]['id'] = 'host.fully_accepted_by_human'
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
            with self.assertRaisesRegex(ValueError, 'Unknown producer'):
                self.metric.host_report(path, self.metric.product_hashes())
        data['cases'][0]['id'] = 'host.discovery'
        data['cases'][0]['evidence'] = ['missing.jsonl']
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
            with self.assertRaisesRegex(ValueError, 'Unhashed host evidence'):
                self.metric.host_report(path, self.metric.product_hashes())

    def test_host_escaped_paths_are_rejected(self):
        path, data = self.host_report()
        data['transcript_files'] = {'../outside.txt': '0' * 64}
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
            with self.assertRaisesRegex(ValueError, 'escapes'):
                self.metric.host_report(path, self.metric.product_hashes())

    def test_blocked_host_prerequisite_remains_in_fixed_denominator(self):
        path, data = self.host_report()
        data['cases'][0]['verdict'] = 'BLOCKED'
        data['cases'][0]['observed'] = {'reason': 'Host unavailable'}
        path.write_text(json.dumps(data), encoding='utf-8')
        with patch.object(self.metric, '__file__', str(self.directory / 'acceptance.py')):
            report = self.metric.host_report(path, self.metric.product_hashes())
        rubric = self.metric.read_json(self.metric.RUBRIC)
        item = next(i for i in rubric['outcomes'] if i['id'] == 'SETUP.host_discovery')
        self.assertEqual(self.metric.outcome(item, [report])['verdict'], 'BLOCKED')
        self.assertEqual(rubric['denominator'], 54)

    def test_unknown_source_check_and_stale_producer_are_rejected(self):
        path, data = self.report(['made.up.acceptance'])
        result = self.command('--source-report', path, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('Unknown producer check', result.stderr)
        path, data = self.report()
        data['source_hashes']['.agents/skills/verify-twinaatma/scripts/verify.py'] = '0' * 64
        path.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--source-report', path, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('producer hash', result.stderr)

    def test_snapshot_refuses_overwriting_prior_evidence(self):
        output = self.directory / 'score.json'
        self.assertEqual(self.command('--output', output).returncode, 0)
        before = output.read_bytes()
        result = self.command('--output', output)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, output.read_bytes())

    def test_rubric_change_or_forged_baseline_counts_prevents_comparison(self):
        before = self.directory / 'before.json'
        self.command('--output', before)
        data = json.loads(before.read_text(encoding='utf-8'))
        data['rubric_sha256'] = '0' * 64
        before.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--baseline', before, '--output', self.directory / 'after.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('rubric', result.stderr)
        data['rubric_sha256'] = self.metric.sha(self.metric.RUBRIC)
        data['counts']['PASS'] = 54
        before.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--baseline', before, '--output', self.directory / 'after.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('counts', result.stderr)

    def test_lost_proof_is_reported_as_regression_not_silently_retained(self):
        report, _ = self.report()
        before = self.directory / 'before.json'
        self.assertEqual(self.command('--source-report', report, '--output', before).returncode, 0)
        after = self.directory / 'after.json'
        result = self.command('--baseline', before, '--output', after)
        self.assertEqual(result.returncode, 0, result.stderr)
        score = json.loads(after.read_text(encoding='utf-8'))
        self.assertEqual(score['comparison']['regressed'], ['SETUP.source_ready'])
        self.assertLess(score['comparison']['fulfillment_percentage_point_change'], 0)


    def test_empty_observation_is_not_machine_proof(self):
        report, data = self.report()
        data['checks'][0]['observed'] = None
        report.write_text(json.dumps(data), encoding='utf-8')
        result = self.command('--source-report', report, '--output', self.directory / 'score.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('literal observed', result.stderr)



    def artifact_report(self, platform="Windows", kind="wheel"):
        directory = self.directory / (platform + "-" + kind)
        directory.mkdir(exist_ok=True)
        producer = self.directory / "artifact.py"
        producer.write_text("# Unit fixture producer, not product evidence.\n", encoding="utf-8")
        current = self.metric.product_hashes()
        assets = {p.relative_to(ROOT).as_posix(): self.metric.sha(p)
                  for name in ("Templates", ".cursor") for p in (ROOT / name).rglob("*")
                  if p.is_file() and not any(part in {"__pycache__", ".git", ".knowledgeos", "node_modules"}
                                             for part in p.relative_to(ROOT).parts) and p.suffix != ".pyc"}
        assets.update({name: self.metric.sha(ROOT / name) for name in ("AGENTS.md", "LICENSE")})
        inputs = dict(assets, **current)
        inputs.update({name: self.metric.sha(ROOT / name) for name in
                       ("knowledgeos/py.typed", "setup.py", "pyproject.toml", "pyinstaller.spec",
                        "MANIFEST.in", "README.md", "knowledgeos.config.example.json")})
        distribution = directory / "distribution"
        distribution.mkdir(exist_ok=True)
        launcher = directory / "venv" / "bin" / "twinaatma"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_bytes(b"unit fixture launcher")
        installation = {"platform": platform + "-unit-fixture", "executable": str(launcher),
                        "vault": str(directory / "vault")}
        Path(installation["vault"]).mkdir(exist_ok=True)
        if kind == "wheel":
            artifact = distribution / "fixture.whl"
            with zipfile.ZipFile(artifact, "w") as wheel:
                wheel_inputs = {p: h for p, h in current.items() if p.startswith("knowledgeos/")}
                wheel_inputs["knowledgeos/py.typed"] = inputs["knowledgeos/py.typed"]
                wheel_inputs.update({"knowledgeos/_assets/" + p: h for p, h in assets.items()})
                for member in wheel_inputs:
                    relative = member.removeprefix("knowledgeos/_assets/")
                    wheel.writestr(member, (ROOT / relative).read_bytes())
            package = directory / "venv" / "lib" / "site-packages" / "knowledgeos"
            for relative in wheel_inputs:
                member = package.parent / relative
                member.parent.mkdir(parents=True, exist_ok=True)
                source = relative.removeprefix("knowledgeos/_assets/")
                member.write_bytes((ROOT / source).read_bytes())
            installation["import_origin"] = str(package / "__init__.py")
            installation["file_hashes"] = {str(p): self.metric.sha(p) for p in [launcher, *package.rglob("*")] if p.is_file()}
            files = {artifact.name: self.metric.sha(artifact)}
            manifest = {"producer": "verify-twinaatma.build/v1", "product_hashes": current,
                        "inputs": inputs, "build_commands": [{"command": ["fixture-build"], "exit_code": 0}],
                        "wheel": str(artifact)}
            (directory / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        else:
            artifact = distribution / "twinaatma"
            artifact.write_bytes(b"unit fixture binary")
            (distribution / "runtime.dll").write_bytes(b"unit fixture dependency")
            for relative in (*assets, "README.md", "knowledgeos.config.example.json"):
                member = distribution / "_internal" / relative
                member.parent.mkdir(parents=True, exist_ok=True)
                member.write_bytes((ROOT / relative).read_bytes())
            launcher = artifact
            installation["executable"] = str(launcher)
            files = {p.relative_to(distribution).as_posix(): self.metric.sha(p)
                     for p in distribution.rglob("*") if p.is_file()}
            manifest = {"producer": "verify-twinaatma.build/v1", "product_hashes": current,
                        "inputs": inputs, "build_commands": [{"command": ["fixture-build"], "exit_code": 0}],
                        "outputs": files, "links": {}, "distribution_root": str(distribution), "executable": str(artifact)}
            (directory / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (directory / "observed.txt").write_text("unit fixture observation\n", encoding="utf-8")
        config = 'command = ' + json.dumps(str(launcher)) + '\nargs = ' + json.dumps(["mcp", "--vault", installation["vault"]]) + '\n'
        (directory / "generated-config.toml").write_text("[mcp_servers.knowledgeos]\n" + config, encoding="utf-8")
        transcripts = {p.name: self.metric.sha(p) for p in directory.iterdir() if p.is_file() and p.name != "report.json"}
        ids = self.metric.ARTIFACT_IDS - {"artifact.execution"}
        if kind == "binary":
            ids = ids - {"artifact.isolated_import"}
        data = {"producer": "verify-twinaatma.artifact/v1", "producer_sha256": self.metric.sha(producer),
                "product_hashes": current, "source_bound": True, "product_unchanged": True, "artifact_unchanged": True,
                "artifact": {"kind": kind, "path": str(artifact), "sha256": self.metric.sha(artifact),
                             "distribution_root": str(distribution), "distribution_files": files, "distribution_links": {}},
                "installation": installation, "transcript_files": transcripts,
                "cases": [{"id": i, "verdict": "PASS", "expected": "fixture expectation", "observed": "literal fixture", "evidence": ["observed.txt"]} for i in ids],
                "processes": [{"pid": 123, "stopped": True}], "all_started_processes_stopped": True,
                "isolation": {"before": {"fixture": "same"}, "after": {"fixture": "same"}, "unchanged": True}}
        path = directory / "report.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path, data

    def parse_artifact(self, path):
        with patch.object(self.metric, "__file__", str(self.directory / "acceptance.py")):
            return self.metric.artifact_report(path, self.metric.product_hashes())

    def test_wheel_stale_or_removed_template_cannot_retain_acceptance(self):
        for replacement in (b"stale template", None):
            with self.subTest(replacement=replacement):
                path, data = self.artifact_report()
                artifact = Path(data["artifact"]["path"])
                with zipfile.ZipFile(artifact) as wheel:
                    entries = {name: wheel.read(name) for name in wheel.namelist()}
                member = "knowledgeos/_assets/Templates/t-person.md"
                if replacement is None:
                    del entries[member]
                else:
                    entries[member] = replacement
                with zipfile.ZipFile(artifact, "w") as wheel:
                    for name, content in entries.items():
                        wheel.writestr(name, content)
                data["artifact"]["sha256"] = self.metric.sha(artifact)
                data["artifact"]["distribution_files"][artifact.name] = self.metric.sha(artifact)
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "assets|product bytes"):
                    self.parse_artifact(path)

    def test_stale_missing_or_extra_build_inputs_cannot_retain_artifact_acceptance(self):
        for kind in ("wheel", "binary"):
            for change in ("stale", "missing", "extra"):
                with self.subTest(kind=kind, change=change):
                    path, data = self.artifact_report(kind=kind)
                    manifest_path = path.parent / "build-manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if change == "stale":
                        manifest["inputs"]["setup.py"] = "0" * 64
                    elif change == "missing":
                        del manifest["inputs"]["Templates/t-person.md"]
                    else:
                        manifest["inputs"]["Templates/removed-template.md"] = "0" * 64
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    data["transcript_files"]["build-manifest.json"] = self.metric.sha(manifest_path)
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "build input"):
                        self.parse_artifact(path)

    def test_binary_stale_missing_or_extra_shipped_assets_are_rejected(self):
        for change in ("stale", "missing", "extra"):
            with self.subTest(change=change):
                path, data = self.artifact_report(kind="binary")
                root = Path(data["artifact"]["distribution_root"])
                template = root / "_internal/Templates/t-person.md"
                if change == "stale":
                    template.write_text("stale template", encoding="utf-8")
                elif change == "missing":
                    template.unlink()
                else:
                    (root / "_internal/Templates/removed-template.md").write_text("extra", encoding="utf-8")
                files = {p.relative_to(root).as_posix(): self.metric.sha(p) for p in root.rglob("*") if p.is_file()}
                data["artifact"]["distribution_files"] = files
                manifest_path = path.parent / "build-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["outputs"] = files
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                data["transcript_files"]["build-manifest.json"] = self.metric.sha(manifest_path)
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "shipped assets"):
                    self.parse_artifact(path)

    def test_installed_extra_product_module_or_stale_asset_cannot_be_bound_as_current(self):
        for target in ("unexpected.py", "_assets/Templates/t-person.md"):
            with self.subTest(target=target):
                path, data = self.artifact_report()
                package = Path(data["installation"]["import_origin"]).parent
                changed = package / target
                changed.write_text("unverified product", encoding="utf-8")
                data["installation"]["file_hashes"][str(changed)] = self.metric.sha(changed)
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Installed product|shipped assets"):
                    self.parse_artifact(path)

    def test_build_manifest_missing_or_different_wheel_cannot_supply_provenance(self):
        for change in ("missing", "different"):
            with self.subTest(change=change):
                path, data = self.artifact_report()
                manifest_path = path.parent / "build-manifest.json"
                if change == "missing":
                    manifest_path.unlink()
                    del data["transcript_files"]["build-manifest.json"]
                else:
                    other = path.parent / "other.whl"
                    other.write_bytes(b"unrelated artifact")
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["wheel"] = str(other)
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    data["transcript_files"]["build-manifest.json"] = self.metric.sha(manifest_path)
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.parse_artifact(path)

    def test_independent_asset_inventory_matches_literal_starter_kit_and_ignores_build_cache(self):
        source = self.directory / "source"
        for name, content in (("Templates/person.md", "abc"), (".cursor/hooks/start.py", "hook"),
                              (".cursor/hooks.json", "config"), ("AGENTS.md", "contract"), ("LICENSE", "license"),
                              ("Templates/__pycache__/ignored", "cache"), ("Templates/node_modules/ignored", "cache"),
                              (".cursor/.git/ignored", "cache"), (".cursor/.knowledgeos/ignored", "cache"),
                              (".cursor/hooks/start.pyc", "cache")):
            file = source / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        with patch.object(self.metric, "ROOT", source):
            assets = self.metric.shipped_assets()
        self.assertEqual(set(assets), {"Templates/person.md", ".cursor/hooks/start.py", ".cursor/hooks.json", "AGENTS.md", "LICENSE"})
        self.assertEqual(assets["Templates/person.md"], "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_only_complete_fixed_release_matrix_can_award_artifact_install(self):
        paths = [self.artifact_report(platform, kind)[0] for platform, kind in sorted(self.metric.ARTIFACT_MATRIX)]
        rubric_bytes = self.metric.RUBRIC.read_bytes()
        with patch.object(self.metric, "__file__", str(self.directory / "acceptance.py")):
            (self.directory / "acceptance.py").write_text("# Synthetic scorer path for producer fixture.\n", encoding="utf-8")
            missing_linux = self.metric.snapshot([], [], artifact_paths=[p for p in paths if p.parent.name.startswith("Windows")])
            full = self.metric.snapshot([], [], artifact_paths=paths)
        self.assertEqual(missing_linux["outcomes"]["SETUP.artifact_install"]["verdict"], "NOT CHECKED")
        self.assertEqual(full["counts"]["PASS"], 1)
        self.assertEqual(full["outcomes"]["SETUP.artifact_install"]["verdict"], "PASS")
        self.assertEqual(full["outcomes"]["SETUP.host_discovery"]["verdict"], "NOT CHECKED")
        self.assertEqual(full["denominator"], 54)
        self.assertEqual(full["adapter_requirements"]["version"], "verify-twinaatma.adapters/v12")
        self.assertEqual(self.metric.RUBRIC.read_bytes(), rubric_bytes)

    def test_artifact_missing_observation_and_unknown_platform_fail_closed(self):
        for field, value in (("platform", "Darwin-unit-fixture"), ("platform", "Windows")):
            path, data = self.artifact_report()
            data["installation"][field] = value
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "matrix cell"):
                self.parse_artifact(path)
        path, data = self.artifact_report()
        data["cases"][0]["evidence"] = []
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "retained evidence"):
            self.parse_artifact(path)

    def test_stale_artifact_product_producer_and_transcripts_are_rejected(self):
        for target in ("product", "producer", "transcript"):
            with self.subTest(target=target):
                path, data = self.artifact_report()
                if target == "product":
                    data["product_hashes"]["knowledgeos/host_setup.py"] = "0" * 64
                elif target == "producer":
                    data["producer_sha256"] = "0" * 64
                else:
                    (path.parent / "observed.txt").write_text("substituted", encoding="utf-8")
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.parse_artifact(path)

    def test_substituted_wheel_launcher_and_binary_dependency_are_rejected(self):
        for kind in ("wheel", "binary"):
            with self.subTest(kind=kind):
                path, data = self.artifact_report(kind=kind)
                target = Path(data["installation"]["executable"]) if kind == "wheel" else Path(data["artifact"]["distribution_root"]) / "runtime.dll"
                target.write_bytes(b"substituted after observation")
                with self.assertRaisesRegex(ValueError, "launcher|dependency"):
                    self.parse_artifact(path)

    def test_artifact_duplicate_matrix_cell_and_missing_required_check_cannot_pass(self):
        reports = [self.parse_artifact(self.artifact_report(platform, kind)[0]) for platform, kind in sorted(self.metric.ARTIFACT_MATRIX)]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.metric.artifact_matrix([reports[0], reports[0]])
        del reports[0]["checks"]["artifact.capture"]
        matrix = self.metric.artifact_matrix(reports)
        self.assertEqual(matrix["checks"]["artifact.isolated_install_usable"]["verdict"], "FAIL")

    def test_foreign_linux_paths_map_only_known_project_prefix(self):
        file = self.directory / "mapped.txt"
        file.write_text("retained", encoding="utf-8")
        mapped = "/mnt/w/AI-Projects/TwinAatma/" + file.relative_to(ROOT).as_posix()
        self.assertEqual(self.metric.retained_file(mapped), file)
        with self.assertRaises(ValueError):
            self.metric.retained_file("/mnt/c/arbitrary/launcher")

    def test_installed_host_cannot_claim_source_or_unbound_artifact(self):
        path, data = self.host_report()
        producer = self.directory / "installed_host.py"
        producer.write_text("# Unit fixture installed-host producer.\n", encoding="utf-8")
        data.update(producer="verify-twinaatma.installed-host/v1", producer_sha256=self.metric.sha(producer))
        path.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(self.metric, "__file__", str(self.directory / "acceptance.py")):
            with self.assertRaisesRegex(ValueError, "artifact binding"):
                self.metric.host_report(path, self.metric.product_hashes())

    def installed_host_report(self):
        artifact_path, artifact = self.artifact_report()
        path, data = self.host_report()
        producer = self.directory / "installed_host.py"
        producer.write_text("# Unit fixture installed-host producer.\n", encoding="utf-8")
        config = self.directory / "generated-config.toml"
        config.write_bytes((artifact_path.parent / "generated-config.toml").read_bytes())
        data.update(producer="verify-twinaatma.installed-host/v1", producer_sha256=self.metric.sha(producer),
                    server_artifact_bound=True,
                    support_sha256={name: self.metric.sha(self.directory / name) for name in ("host.py", "artifact.py")},
                    artifact_evidence={"report": str(artifact_path), "sha256": self.metric.sha(artifact_path)})
        data.pop("server_source_bound")
        data["transcript_files"]["generated-config.toml"] = self.metric.sha(config)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path, data, artifact

    @unittest.skipIf(sys.version_info < (3, 11), "Native TOML report grading requires Python 3.11+")
    def test_installed_host_pass_is_bound_to_exact_artifact_and_native_launcher(self):
        path, _, _ = self.installed_host_report()
        with patch.object(self.metric, "__file__", str(self.directory / "acceptance.py")):
            report = self.metric.host_report(path, self.metric.product_hashes())
        self.assertEqual(report["scope"], "real_host")
        self.assertEqual(report["producer"], "verify-twinaatma.installed-host/v1")
        item = next(i for i in self.metric.read_json(self.metric.RUBRIC)["outcomes"] if i["id"] == "SETUP.host_discovery")
        self.assertEqual(self.metric.outcome(item, [report])["verdict"], "PASS")

    @unittest.skipIf(sys.version_info < (3, 11), "Native TOML report grading requires Python 3.11+")
    def test_installed_host_stale_support_artifact_and_config_are_rejected(self):
        for target in ("support", "artifact", "config"):
            with self.subTest(target=target):
                path, data, _ = self.installed_host_report()
                if target == "support":
                    data["support_sha256"]["host.py"] = "0" * 64
                elif target == "artifact":
                    data["artifact_evidence"]["sha256"] = "0" * 64
                else:
                    config = self.directory / "generated-config.toml"
                    config.write_text('[mcp_servers.knowledgeos]\ncommand = "python"\nargs = []\n', encoding="utf-8")
                    data["transcript_files"]["generated-config.toml"] = self.metric.sha(config)
                path.write_text(json.dumps(data), encoding="utf-8")
                with patch.object(self.metric, "__file__", str(self.directory / "acceptance.py")):
                    with self.assertRaises(ValueError):
                        self.metric.host_report(path, self.metric.product_hashes())

    @unittest.skipIf(sys.version_info < (3, 11), "Native TOML report grading requires Python 3.11+")
    def test_installed_host_checkout_pythonpath_is_rejected(self):
        path, data, _ = self.installed_host_report()
        config = self.directory / "generated-config.toml"
        with config.open("a", encoding="utf-8") as stream:
            stream.write('[mcp_servers.knowledgeos.env]\nPYTHONPATH = "checkout"\n')
        data["transcript_files"]["generated-config.toml"] = self.metric.sha(config)
        path.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(self.metric, "__file__", str(self.directory / "acceptance.py")):
            with self.assertRaisesRegex(ValueError, "native configuration"):
                self.metric.host_report(path, self.metric.product_hashes())

    def test_unreported_binary_dependency_cannot_hide_in_retained_distribution(self):
        path, data = self.artifact_report(kind="binary")
        (Path(data["artifact"]["distribution_root"]) / "extra.dll").write_bytes(b"unreported dependency")
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.parse_artifact(path)


if __name__ == '__main__':
    unittest.main()
