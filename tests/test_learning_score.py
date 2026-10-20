"""Adversarial adapter controls. Synthetic records never earn product acceptance."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT = next(path for path in Path(__file__).resolve().parents if (path / 'knowledgeos/memory.py').is_file())
SCRIPT = Path(os.environ.get('TWIN_ACCEPTANCE_SCORER', ROOT / '.agents/skills/verify-twinaatma/scripts/acceptance.py'))
SPEC = importlib.util.spec_from_file_location('learning_score_controls', SCRIPT)
metric = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metric)
metric.ROOT = ROOT
metric.RUBRIC = ROOT / '.agents/skills/verify-twinaatma/references/acceptance-rubric.json'


class LearningViews(unittest.TestCase):
    def result(self, paths=('Decisions/NovaPending.md',), *, frozen=False):
        payload = {'decisions': [{'path': path, 'project': 'Nova', 'status': 'active'} for path in paths], 'count': len(paths)}
        if frozen:
            payload.update(index_frozen=True, index_frozen_note='Current source metadata is shown; new notes may be missing.')
        return {'payload': payload, 'is_error': False}

    def expected(self):
        return {'Decisions/NovaPending.md': {'project': 'Nova', 'status': 'active'}}

    def test_literal_registry_and_fixed54_contract(self):
        self.assertEqual(len(metric.LEARNING_IDS), 12)
        self.assertEqual(metric.LEARNING_IDS[1], 'learning.exact_project_filter')
        self.assertEqual(metric.ADAPTER_REQUIREMENTS['version'], 'verify-twinaatma.adapters/v12')
        rubric = metric.read_json(metric.RUBRIC)
        self.assertEqual(len(rubric['outcomes']), 54)
        self.assertEqual(metric.sha(metric.RUBRIC), '744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91')
        self.assertEqual(metric.ADAPTER_REQUIREMENTS['outcomes']['LEARNING.decision_views'], ['learning.decision_views.complete'])
        self.assertEqual(metric.ADAPTER_REQUIREMENTS['outcomes']['LEARNING.attributed_lessons'], ['learning.attributed_lessons.complete'])

    def test_literal_source_project_and_status(self):
        self.assertTrue(metric.learning_view(self.result(), 'decisions', self.expected()))
        for mutate in (lambda result: result['payload']['decisions'][0].update(project='Supernova'),
                       lambda result: result['payload']['decisions'][0].update(path='Decisions/SupernovaPending.md'),
                       lambda result: result['payload']['decisions'][0].update(status='archived')):
            result = self.result()
            mutate(result)
            self.assertFalse(metric.learning_view(result, 'decisions', self.expected()))

    def test_separate_supernova_is_not_a_nova_match(self):
        result = self.result(('Decisions/NovaPending.md', 'Decisions/SupernovaPending.md'))
        self.assertFalse(metric.learning_view(result, 'decisions', self.expected()))

    def test_empty_or_missing_payload_cannot_match_nonempty_expected_sources(self):
        for result in ({}, {'payload': None, 'is_error': False}, self.result(()), {'payload': {}, 'is_error': False}):
            self.assertFalse(metric.learning_view(result, 'decisions', self.expected()))

    def test_duplicate_or_malformed_rows_do_not_disappear(self):
        for rows in ([{'path': 'Decisions/NovaPending.md', 'project': 'Nova', 'status': 'active'}] * 2,
                     [{'path': 'Decisions/NovaPending.md', 'project': 'Nova', 'status': 'active'}, None],
                     [{'path': 'Decisions/NovaPending.md', 'project': 'Nova', 'status': 'active'}, {}]):
            result = self.result()
            result['payload'].update(decisions=rows, count=len(rows))
            self.assertFalse(metric.learning_view(result, 'decisions', self.expected()))

    def test_count_is_literal_integer_and_matches_actual_rows(self):
        for count in (True, 0, 2, '1', None):
            result = self.result()
            result['payload']['count'] = count
            self.assertFalse(metric.learning_view(result, 'decisions', self.expected()))

    def test_frozen_reads_require_explicit_completeness_warning(self):
        self.assertTrue(metric.learning_view(self.result(frozen=True), 'decisions', self.expected(), frozen=True))
        for mutate in (lambda value: value.pop('index_frozen_note'), lambda value: value.update(index_frozen=False),
                       lambda value: value.update(index_frozen_note='Everything is complete.')):
            result = self.result(frozen=True)
            mutate(result['payload'])
            self.assertFalse(metric.learning_view(result, 'decisions', self.expected(), frozen=True))

    def test_retry_removes_frozen_status_and_requires_new_source(self):
        expected = {'Decisions/FreshOrion.md': {'project': 'Orion'}}
        self.assertFalse(metric.learning_view(self.result(), 'decisions', expected))
        self.assertFalse(metric.learning_view(self.result(frozen=True), 'decisions', self.expected()))

    def test_timeline_keeps_initialized_notes_but_rejects_old_synthetic_source(self):
        result = self.result()
        result['payload']['notes'] = result['payload'].pop('decisions')
        result['payload']['notes'].append({'path': 'Decisions/_Index.md', 'title': 'Legitimate initialized note'})
        result['payload']['count'] = 2
        self.assertTrue(metric.learning_view(result, 'notes', self.expected(), synthetic_only=True))
        result['payload']['notes'].append({'path': 'Concepts/LearningOld.md', 'title': 'Old source'})
        result['payload']['count'] = 3
        self.assertFalse(metric.learning_view(result, 'notes', self.expected(), synthetic_only=True))


class AttributedLessons(unittest.TestCase):
    def fixture(self):
        proposal = {'payload': {'ok': True, 'policy': 'proposal_only', 'mutated_self': False, 'section': 'heuristics',
            'proposal_id': 'synthetic-draft-id', 'proposal_path': 'People/Self-Proposals/synthetic-draft.md'}, 'is_error': False}
        opened = {'payload': {'open': [{'path': 'People/Self-Proposals/synthetic-draft.md', 'id': 'synthetic-draft-id', 'status': 'draft'}]}, 'is_error': False}
        text = ('---\nproposal_section: heuristics\nproposal_mode: append\nproposal_target: People/Self.md\nstatus: draft\n---\n'
            '[Synthetic Nova checkpoint](Decisions/NovaComplete.md)\n'
            'For the synthetic Nova pilot, keep a reversible checkpoint before scaling; this is one local observation.\n'
            'This single recorded outcome does not establish a general belief; review before adopting.\n'
            "Decision outcome 'confirmed' records this lesson. Source: Decisions/NovaComplete.md.\n")
        source = metric.learning_note('Decisions/NovaComplete.md', metric.LEARNING_DECISIONS['Decisions/NovaComplete.md']).decode()
        return proposal, opened, text, source

    def test_one_completed_local_source_backs_one_unapproved_draft(self):
        self.assertTrue(metric.learning_proposal(*self.fixture()))

    def test_missing_link_uncertainty_or_local_scope_fails(self):
        proposal, opened, text, source = self.fixture()
        for fragment in ('[Synthetic Nova checkpoint](Decisions/NovaComplete.md)',
                         'This single recorded outcome does not establish a general belief; review before adopting.',
                         "Decision outcome 'confirmed' records this lesson. Source: Decisions/NovaComplete.md.",
                         'proposal_target: People/Self.md', 'status: draft'):
            self.assertFalse(metric.learning_proposal(proposal, opened, text.replace(fragment, ''), source))

    def test_pending_nondecision_or_changed_lesson_cannot_support_proposal(self):
        proposal, opened, text, source = self.fixture()
        for source_text in (source.replace('outcome_status: "confirmed"', 'outcome_status: "pending"'),
                            source.replace('type: decision', 'type: concept'), source.replace(metric.LEARNING_LESSON, 'A different lesson.')):
            self.assertFalse(metric.learning_proposal(proposal, opened, text, source_text))

    def test_missing_duplicate_or_accepted_open_proposals_fail(self):
        proposal, opened, text, source = self.fixture()
        for mutate in (lambda value: value['payload'].update(open=[]),
                       lambda value: value['payload']['open'].append(copy.deepcopy(value['payload']['open'][0])),
                       lambda value: value['payload']['open'][0].update(status='accepted'),
                       lambda value: value['payload']['open'][0].update(id='another-draft'),
                       lambda value: value['payload']['open'][0].update(path='People/Self-Proposals/other.md')):
            value = copy.deepcopy(opened)
            mutate(value)
            self.assertFalse(metric.learning_proposal(proposal, value, text, source))

    def test_duplicate_lesson_or_self_mutation_is_not_a_proposal_only_success(self):
        proposal, opened, text, source = self.fixture()
        self.assertFalse(metric.learning_proposal(proposal, opened, text + metric.LEARNING_LESSON, source))
        for field, value in (('mutated_self', True), ('policy', 'accepted'), ('section', 'values'), ('ok', False)):
            changed = copy.deepcopy(proposal)
            changed['payload'][field] = value
            self.assertFalse(metric.learning_proposal(changed, opened, text, source))

    def test_source_only_learning_cannot_prove_host_owner_or_longitudinal_outcomes(self):
        report = {'path': 'synthetic control', 'report_sha256': 'a' * 64, 'scope': 'source', 'checks': {
            'learning.decision_views.complete': {'id': 'learning.decision_views.complete', 'verdict': 'PASS'},
            'learning.attributed_lessons.complete': {'id': 'learning.attributed_lessons.complete', 'verdict': 'PASS'}}}
        identifiers = {'LEARNING.host_outcome_loop', 'LEARNING.semantic_drift', 'LEARNING.rejection_recurrence', 'IDENTITY.owner_exact_approval'}
        items = [item for item in metric.read_json(metric.RUBRIC)['outcomes'] if item['id'] in identifiers]
        self.assertEqual({item['id'] for item in items}, identifiers)
        for item in items:
            self.assertEqual(metric.outcome(item, [report])['verdict'], 'NOT CHECKED')


if __name__ == '__main__':
    unittest.main()
