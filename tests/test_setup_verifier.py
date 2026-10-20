"""Public CLI proof for configuration preservation and honest partial setup."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / '.agents/skills/verify-twinaatma/scripts/verify.py'
spec = importlib.util.spec_from_file_location('setup_verification', SCRIPT)
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class SetupVerificationTests(unittest.TestCase):
    def setUp(self):
        self.run = verification.Run(ROOT / 'work/gc-artifacts/.knowledgeos/runtime-hooks-20261019/setup-worker')
        self.run.vault.mkdir()
        (self.run.vault / 'untouched.txt').write_bytes(b'Main fixture unchanged.\n')

    def tearDown(self):
        (self.run.directory / 'worker-checks.json').write_text(
            json.dumps({'checks': self.run.checks, 'processes': self.run.processes}, indent=2), encoding='utf-8')

    def test_public_setup_preserves_all_host_configs_and_refuses_invalid_bytes(self):
        self.run.setup_configurations()
        check, = self.run.checks
        self.assertEqual(check['id'], 'setup.config_preserved')
        self.assertEqual(check['verdict'], 'PASS', check['observed'])
        self.assertEqual(len(check['observed']), 21)
        for host in ('cursor', 'vscode', 'codex'):
            cases = [case for case in check['observed'] if case['host'] == host]
            self.assertEqual(len(cases), 7)
            self.assertTrue(all(case['passed'] for case in cases), cases)
        self.assertEqual((self.run.vault / 'untouched.txt').read_bytes(), b'Main fixture unchanged.\n')
        rows = [json.loads(line) for line in (self.run.directory / 'transcript.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(row['vault'] != str(self.run.vault) for row in rows))
        self.assertTrue(all(row['vault'] == row['command'][row['command'].index('--vault') + 1] for row in rows))
        self.assertEqual(self.run.env['KNOWLEDGEOS_VAULT'], str(self.run.vault))

    def test_public_init_reports_partial_failure_without_overwriting_obstruction(self):
        self.run.setup_post_init_failure()
        check, = self.run.checks
        self.assertEqual(check['id'], 'setup.post_init_failure')
        self.assertEqual(check['verdict'], 'PASS', check['observed'])
        observed = check['observed']
        self.assertEqual(observed['exit_code'], 1)
        self.assertIs(observed['report']['ok'], False)
        self.assertIs(observed['report']['post_init']['rebuild']['ok'], False)
        self.assertIs(observed['obstruction_preserved'], True)
        self.assertIs(observed['partial_self_exists'], True)
        self.assertEqual((self.run.vault / 'untouched.txt').read_bytes(), b'Main fixture unchanged.\n')
        row, = [json.loads(line) for line in (self.run.directory / 'transcript.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertNotEqual(row['vault'], str(self.run.vault))
        self.assertEqual(row['vault'], row['command'][row['command'].index('init') + 1])
        self.assertEqual(self.run.env['KNOWLEDGEOS_VAULT'], str(self.run.vault))

    def test_partial_failure_cannot_pass_when_cli_reports_success(self):
        real_command = self.run.command

        def misleading_success(*arguments, **keywords):
            result = real_command(*arguments, **keywords)
            result.returncode = 0
            return result

        with patch.object(self.run, 'command', side_effect=misleading_success):
            self.run.setup_post_init_failure()
        self.assertEqual(self.run.checks[0]['verdict'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
