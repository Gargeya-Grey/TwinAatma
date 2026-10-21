"""The CI-graded route: attested runner bundles are refused unless every binding holds, and their rows count.

Only the GitHub CLI boundary (`ci_graded.run_gh`) is replaced. The importer, the grading-side matrix
functions, snapshot() and the writer bundle all run for real.
"""
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.agents/skills/verify-twinaatma/scripts'
sys.path.insert(0, str(SCRIPTS))

import ci_graded  # noqa: E402
import identity_writers_grade as writers_grade  # noqa: E402

REPO = 'Gargeya-Grey/TwinAatma'
RUN = ('4242', '1')


def load_scorer():
    spec = importlib.util.spec_from_file_location('acceptance_under_test', SCRIPTS / 'acceptance.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # snapshot() passes sys.modules[__name__] to the importer
    spec.loader.exec_module(module)
    return module


def lf(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def rows(ids, verdict='PASS'):
    return {name: {'id': name, 'verdict': verdict, 'expected': 'literal expectation',
                   'observed': {'literal': True}, 'evidence': ['evidence.txt']} for name in sorted(ids)}


class CiGradedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metric = load_scorer()
        cls.current = cls.metric.product_hashes()
        cls.head = ci_graded.git_head(ROOT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        patcher = mock.patch.dict(os.environ, {'GH_TOKEN': 'not-a-real-token'})
        patcher.start()
        self.addCleanup(patcher.stop)

    # ------------------------------------------------------------------ builders (data only)
    def report(self, **fields):
        report = {'path': '/runner/work/report.json', 'report_sha256': '0' * 64, 'scope': 'artifact'}
        report.update(fields)
        return report

    def artifact(self, system, kind, verdict='PASS'):
        return self.report(cell=[system, kind], producer='verify-twinaatma.artifact/v1',
                           checks=rows(self.metric.ARTIFACT_IDS, verdict))

    def hook(self, system, kind, minor, verdict='PASS', fail=None):
        checks = rows(self.metric.HOOK_IDS)
        if fail:
            checks[fail] = dict(checks[fail], verdict='FAIL')
        return self.report(cell=[system, kind, minor], producer='verify-twinaatma.runtime-hooks/v1', checks=checks)

    def hooks(self, system, fail_cell=None):
        cells = [(system, 'wheel', minor) for minor in self.metric.RUNTIME_MINORS] + [(system, 'binary', 'embedded')]
        return [self.hook(*cell, fail='hook.init' if cell == fail_cell else None) for cell in cells]

    def hooks_data(self):
        spec = self.metric.ALL_DATA_PRODUCERS['verify-twinaatma.hooks-preservation/v1']
        checks = rows(spec['cases'])
        checks[spec['aggregate']] = {'id': spec['aggregate'], 'verdict': 'PASS', 'observed': {'complete': True}}
        return self.report(scope='source', producer='verify-twinaatma.hooks-preservation/v1', checks=checks)

    def write_faults(self):
        aggregate = 'recovery.write-faults.complete'
        return self.report(scope='source', producer='verify-twinaatma.recovery-write-faults/v1',
                           checks={aggregate: {'id': aggregate, 'verdict': 'PASS'}})

    def linux_graded(self):
        return {'artifacts': [self.artifact('Linux', 'wheel'), self.artifact('Linux', 'binary')],
                'hooks': self.hooks('Linux'), 'data': [self.hooks_data()], 'recovery': [self.write_faults()]}

    def windows_graded(self, fail_cell=None):
        return {'hooks': self.hooks('Windows', fail_cell)}

    def bundle(self, graded, system='Linux', **binding_changes):
        binding = ci_graded.local_binding(self.metric)
        binding.update({'repository': REPO, 'run_id': RUN[0], 'run_attempt': RUN[1],
                        'platform': {'system': system, 'os_name': 'posix' if system == 'Linux' else 'nt'}})
        binding.update(binding_changes)
        data = {'schema': ci_graded.SCHEMA, 'binding': binding, 'raw_reports': {'work/r/report.json': 'a' * 64},
                'rejected': [], 'graded': graded,
                'graded_sha256': hashlib.sha256(ci_graded.canonical(graded).encode()).hexdigest()}
        return data

    def save(self, data, name='bundle.json'):
        path = self.directory / name
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding='utf-8')
        return path

    # ------------------------------------------------------------------ the attestation boundary
    def gh(self, *, commit=None, ok=True, run=RUN, signer=None):
        commit = commit or self.head
        certificate = {'sourceRepositoryDigest': commit, 'sourceRepositoryURI': 'https://github.com/' + REPO,
                       'runInvocationURI': 'https://github.com/{}/actions/runs/{}/attempts/{}'.format(REPO, *run),
                       'buildSignerURI': 'https://github.com/{}/{}@refs/heads/acceptance/ci-evidence'.format(
                           REPO, signer or ci_graded.WORKFLOW),
                       'sourceRepositoryRef': 'refs/heads/acceptance/ci-evidence'}
        payload = json.dumps([{'verificationResult': {'signature': {'certificate': certificate}}}])

        def fake(command, env):
            self.assertEqual(command[:3], ['gh', 'attestation', 'verify'])
            self.assertIn('--repo', command)
            if not ok:
                return subprocess.CompletedProcess(command, 1, '', 'verification failed: no attestations found')
            return subprocess.CompletedProcess(command, 0, payload, '')
        return mock.patch.object(ci_graded, 'run_gh', side_effect=fake)

    def imported(self, *bundles, **gh_options):
        paths = [self.save(bundle, 'bundle-%d.json' % index) for index, bundle in enumerate(bundles)]
        with self.gh(**gh_options):
            return ci_graded.import_bundles(paths, self.metric, self.current)

    def refused(self, bundle, message, **gh_options):
        with self.assertRaises(ValueError) as caught:
            self.imported(bundle, **gh_options)
        self.assertIn(message, str(caught.exception))

    # ------------------------------------------------------------------ importer refusals
    def test_valid_bundle_imports_with_independently_computed_binding(self):
        bundle = self.bundle(self.linux_graded())
        expected = {name: lf(ROOT / name) for name in self.current}
        self.assertEqual(bundle['binding']['product_hashes_lf'], expected)
        result = self.imported(bundle)
        self.assertEqual((len(result['artifacts']), len(result['hooks']), len(result['reports'])), (2, 7, 2))
        self.assertEqual(result['writers'], {})

    def test_wrong_commit_is_refused(self):
        wrong = 'f' * 40
        self.refused(self.bundle(self.linux_graded(), commit=wrong), 'commit differs', commit=wrong)

    def test_attestation_for_another_commit_is_refused(self):
        self.refused(self.bundle(self.linux_graded()), 'does not match the bundle', commit='e' * 40)

    def test_attestation_from_another_run_is_refused(self):
        self.refused(self.bundle(self.linux_graded()), 'does not match the bundle', run=('7', '1'))

    def test_attestation_from_another_workflow_is_refused(self):
        self.refused(self.bundle(self.linux_graded()), 'does not match the bundle', signer='.github/workflows/ci.yml')

    def test_stale_product_hash_is_refused(self):
        bundle = self.bundle(self.linux_graded())
        name = sorted(bundle['binding']['product_hashes_lf'])[0]
        bundle['binding']['product_hashes_lf'][name] = '0' * 64
        self.refused(bundle, 'product hashes differ')

    def test_stale_toolkit_hash_is_refused(self):
        bundle = self.bundle(self.linux_graded())
        bundle['binding']['toolkit_hashes_lf'].pop(sorted(bundle['binding']['toolkit_hashes_lf'])[0])
        self.refused(bundle, 'product hashes differ')

    def test_different_scorer_hash_is_refused(self):
        self.refused(self.bundle(self.linux_graded(), scorer_sha256_lf='1' * 64), 'scorer_sha256_lf')

    def test_different_adapter_requirements_hash_is_refused(self):
        self.refused(self.bundle(self.linux_graded(), adapter_requirements_sha256_lf='2' * 64), 'adapter_requirements_sha256_lf')

    def test_unattested_bundle_is_refused(self):
        self.refused(self.bundle(self.linux_graded()), 'Attestation verification failed', ok=False)

    def test_altered_row_is_refused(self):
        bundle = self.bundle(self.linux_graded())
        bundle['graded']['hooks'][0]['checks']['hook.init']['verdict'] = 'FAIL'
        self.refused(bundle, 'altered after grading')

    def test_forged_pass_without_observation_is_refused(self):
        graded = self.linux_graded()
        graded['artifacts'][0]['checks']['artifact.init']['observed'] = {}
        self.refused(self.bundle(graded), 'PASS without an observed result')

    def test_cell_from_the_other_platform_is_refused(self):
        graded = {'hooks': [self.hook('Windows', 'wheel', '3.9')]}
        self.refused(self.bundle(graded), 'outside this platform')

    def test_unknown_check_id_is_refused(self):
        graded = self.linux_graded()
        graded['artifacts'][0]['checks']['host.grounded_answer'] = {'id': 'host.grounded_answer', 'verdict': 'PASS', 'observed': 1}
        self.refused(self.bundle(graded), 'unknown or mismatched check')

    def test_a_host_or_human_scoped_row_is_refused(self):
        graded = self.linux_graded()
        graded['artifacts'][0]['scope'] = 'real_host'
        self.refused(self.bundle(graded), 'wrong scope')

    def test_the_same_bundle_twice_is_refused(self):
        bundle = self.bundle(self.linux_graded())
        with self.assertRaises(ValueError) as caught:
            self.imported(bundle, copy.deepcopy(bundle))
        self.assertIn('twice', str(caught.exception))

    def test_attestation_parser_never_prints_the_token(self):
        with self.gh(ok=False):
            with self.assertRaises(ValueError) as caught:
                ci_graded.verify_attestation(self.save({}), REPO)
        self.assertNotIn('not-a-real-token', str(caught.exception))

    # ------------------------------------------------------------------ rows feed the real scorer
    def test_windows_rows_plus_imported_linux_rows_complete_the_matrices(self):
        windows_artifacts = [self.artifact('Windows', 'wheel'), self.artifact('Windows', 'binary')]
        self.assertEqual(self.metric.artifact_matrix(windows_artifacts)['checks']['artifact.release_matrix_complete']['verdict'], 'NOT CHECKED')
        linux = self.imported(self.bundle(self.linux_graded()))
        matrix = self.metric.artifact_matrix(windows_artifacts + linux['artifacts'])['checks']
        self.assertEqual({row['verdict'] for row in matrix.values()}, {'PASS'})
        windows = self.imported(self.bundle(self.windows_graded(), 'Windows'))
        self.assertEqual(self.metric.runtime_hook_matrix(windows['hooks'])['checks']['hook.runtime_matrix_complete']['verdict'], 'NOT CHECKED')
        both = self.imported(self.bundle(self.linux_graded()), self.bundle(self.windows_graded(), 'Windows'))
        hooks = self.metric.runtime_hook_matrix(both['hooks'])['checks']
        self.assertEqual({row['verdict'] for row in hooks.values()}, {'PASS'})

    def snapshot(self, *bundles, **gh_options):
        paths = [self.save(bundle, 'bundle-%d.json' % index) for index, bundle in enumerate(bundles)]
        with self.gh(**gh_options):
            return self.metric.snapshot([], [], ci_graded_paths=paths)

    def test_snapshot_awards_the_runtime_hook_outcome_from_two_bundles(self):
        result = self.snapshot(self.bundle(self.linux_graded()), self.bundle(self.windows_graded(), 'Windows'))
        self.assertEqual(result['outcomes']['SETUP.runtime_hooks']['verdict'], 'PASS')
        self.assertEqual(result['outcomes']['SETUP.artifact_install']['verdict'], 'NOT CHECKED')
        self.assertEqual(result['outcomes']['RECOVERY.ownership_locks']['verdict'], 'NOT CHECKED')
        self.assertEqual(result['outcomes']['DATA.preserve_hooks']['verdict'], 'PASS')

    def test_a_fail_row_stays_fail(self):
        result = self.snapshot(self.bundle(self.linux_graded()),
                               self.bundle(self.windows_graded(('Windows', 'wheel', '3.11')), 'Windows'))
        self.assertEqual(result['outcomes']['SETUP.runtime_hooks']['verdict'], 'FAIL')
        failing = [row for row in result['outcomes']['SETUP.runtime_hooks']['evidence'] if row['verdict'] == 'FAIL']
        self.assertTrue(failing)

    def test_a_fail_row_cannot_be_hidden_by_a_passing_cell(self):
        graded = self.linux_graded()
        graded['data'][0]['checks']['data.hooks.complete'] = {'id': 'data.hooks.complete', 'verdict': 'FAIL', 'observed': {'complete': True}}
        result = self.snapshot(self.bundle(graded))
        self.assertEqual(result['outcomes']['DATA.preserve_hooks']['verdict'], 'FAIL')

    def test_a_not_checked_row_beside_a_pass_row_is_not_a_pass(self):
        # Why the laptop's Windows hooks report (two NOT CHECKED symlink cases) is not supplied beside the CI one.
        graded = self.linux_graded()
        windows_like = self.hooks_data()
        windows_like['checks']['data.hooks.complete'] = {'id': 'data.hooks.complete', 'verdict': 'NOT CHECKED', 'observed': {'complete': False}}
        reports = [windows_like, self.imported(self.bundle(graded))['reports'][0]]
        item = next(row for row in json.loads(self.metric.RUBRIC.read_text(encoding='utf-8-sig'))['outcomes'] if row['id'] == 'DATA.preserve_hooks')
        self.assertEqual(self.metric.outcome(item, reports)['verdict'], 'NOT CHECKED')
        self.assertEqual(self.metric.outcome(item, reports[1:])['verdict'], 'PASS')

    # ------------------------------------------------------------------ pre-graded writer platform
    def focused(self, os_name):
        return {'path': '/runner/' + os_name, 'report_sha256': 'b' * 64, 'os_name': os_name, 'verdict': 'PASS', 'cases': 1,
                'actual_tools': [], 'actual_scripts': [], 'nested_processes': [], 'safe_manifest_detachments': [],
                'known_product_refusals': [], 'successful_refreshes': []}

    def test_writer_bundle_still_needs_both_native_platforms(self):
        with self.assertRaises(ValueError) as caught:
            writers_grade.bundle([], base=self.metric, current=self.current,
                                 pregraded={'focused': [self.focused('posix')]})
        self.assertIn('both required', str(caught.exception))

    def test_pregraded_platform_passes_the_platform_check_and_meets_the_remaining_ones(self):
        with self.assertRaises(ValueError) as caught:
            writers_grade.bundle([], base=self.metric, current=self.current,
                                 pregraded={'focused': [self.focused('posix'), self.focused('nt')]})
        self.assertIn('lacks complete current public writer evidence', str(caught.exception))

    def test_writer_rows_import_only_from_their_own_platform(self):
        graded = {'writers': {'focused': [self.focused('nt')]}}
        self.refused(self.bundle(graded), 'another platform')
        result = self.imported(self.bundle({'writers': {'focused': [self.focused('posix')]},
                                            'recovery': [self.write_faults()]}))
        self.assertEqual(set(result['writers']), {'focused', 'reused', 'recovery'})


if __name__ == '__main__':
    unittest.main()
