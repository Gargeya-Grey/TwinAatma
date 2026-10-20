import json
import unittest
from support import TempVaultCase

class SessionRepairTests(TempVaultCase):
    def test_repeated_corrupt_state_preserves_each_original_payload(self):
        from knowledgeos.autopilot import state_dir
        api = self.api()
        directory = state_dir(self.vault)
        path = directory / 'autopilot.json'
        damaged = (b'{first interrupted session', b'\xffsecond interrupted session')
        for index, payload in enumerate(damaged):
            path.write_bytes(payload)
            result = api.session_start('Recover session', session_id='corrupt-' + str(index))
            self.assertNotIn('error', result)
        retained = [item.read_bytes() for item in directory.glob('autopilot.json.corrupt*') if item.is_file()]
        self.assertCountEqual(retained, damaged)

    def test_corrupt_state_recovery_preserves_an_existing_backup_directory(self):
        from knowledgeos.autopilot import state_dir
        api = self.api()
        directory = state_dir(self.vault)
        obstruction = directory / 'autopilot.json.corrupt'
        obstruction.mkdir()
        held = obstruction / 'retained.bin'
        held.write_bytes(b'earlier recovery evidence')
        original = b'{interrupted before state commit'
        (directory / 'autopilot.json').write_bytes(original)
        api.session_start('Recover safely', session_id='obstructed')
        self.assertEqual(held.read_bytes(), b'earlier recovery evidence')
        retained = [item.read_bytes() for item in directory.glob('autopilot.json.corrupt*') if item.is_file()]
        self.assertEqual(retained, [original])

    def test_failed_recovery_copy_keeps_original_state_and_refuses_reset(self):
        from unittest import mock
        from knowledgeos.autopilot import state_dir
        api = self.api()
        api.session_start('Prepare state', session_id='before')
        path = state_dir(self.vault) / 'autopilot.json'
        original = b'{recovery storage unavailable'
        path.write_bytes(original)
        with mock.patch('knowledgeos.textio.atomic_create_bytes', side_effect=OSError('recovery copy unavailable')):
            with self.assertRaisesRegex(OSError, 'recovery copy unavailable'):
                api.session_start('Do not reset', session_id='blocked')
        self.assertEqual(path.read_bytes(), original)

    def test_failed_capture_keeps_session_recoverable(self):
        api=self.api()
        api.session_start('Save important work')
        (self.vault/'Inbox').rename(self.vault/'retained-inbox')
        (self.vault/'Inbox').write_text('Storage unavailable',encoding='utf-8')
        result=api.session_end('A summary that must not be lost')
        self.assertIn('error',result)
        state=json.loads((self.vault/'.knowledgeos/autopilot.json').read_text(encoding='utf-8'))
        self.assertFalse(state.get('session_ended'))
        self.assertEqual(state.get('sessions_completed',0),0)
        self.assertIn('error',api.session_end())
        (self.vault/'Inbox').unlink()
        (self.vault/'retained-inbox').rename(self.vault/'Inbox')
        first=api.session_end('A summary that must not be lost')
        replay=api.session_end('A summary that must not be lost')
        self.assertEqual(first['captured']['path'],replay['captured']['path'])
        self.assertEqual(len(list((self.vault/'Inbox').glob('capture-*.md'))),1)

    def test_preference_prompt_is_not_repeated_at_wrap(self):
        api=self.api()
        proposal=api.propose_self_update('Prefer evidence','heuristics','* Prefer evidence.',mode='append')
        self.assertIn('proposal_path',proposal)
        start=api.session_start('Work')
        self.assertTrue(start['soft_prompt'])
        end=api.session_end('Useful result')
        self.assertIsNone(end['soft_prompt'])
        self.assertIsNone(api.session_start('Next chat')['soft_prompt'])

    def test_named_sessions_are_independent_and_end_retries_are_idempotent(self):
        from knowledgeos.memory import dispatch
        api=self.api()
        a=dispatch(api,'memory_session_start',{'session_id':'chat-a','task_hint':'A'})
        self.assertEqual(a.get('session_id'),'chat-a')
        dispatch(api,'memory_session_start',{'session_id':'chat-a','task_hint':'A'})
        dispatch(api,'memory_session_start',{'session_id':'chat-b','task_hint':'B'})
        first=dispatch(api,'memory_session_end',{'session_id':'chat-a','summary':'Unique alpha summary'})
        again=dispatch(api,'memory_session_end',{'session_id':'chat-a','summary':'Unique alpha summary'})
        self.assertEqual(first['captured']['path'],again['captured']['path'])
        state=json.loads((self.vault/'.knowledgeos/autopilot.json').read_text(encoding='utf-8'))
        self.assertEqual(state['real_sessions'],2)
        self.assertEqual(state['sessions_completed'],1)
        self.assertTrue(state['session_open'])
        self.assertEqual(state['sessions']['chat-b']['status'],'open')
        self.assertEqual(state['sessions']['chat-a']['status'],'ended')
        conflict=dispatch(api,'memory_session_end',{'session_id':'chat-a','summary':'Different summary'})
        self.assertIn('error',conflict)

    def test_concurrent_same_title_captures_preserve_every_body(self):
        import concurrent.futures, threading
        from knowledgeos.memory import MemoryAPI
        barrier=threading.Barrier(20)
        def capture(i):
            barrier.wait(timeout=15)
            return MemoryAPI(self.vault).capture('Same title','Unique body number '+str(i))
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            captures=list(executor.map(capture,range(20)))
        self.assertTrue(all(c.get('ok') for c in captures),captures)
        self.assertEqual(len({c['path'] for c in captures}),20)
        for i,c in enumerate(captures):
            self.assertIn('Unique body number '+str(i)+'\n',(self.vault/c['path']).read_text(encoding='utf-8'))

    def test_orphan_prompt_is_once_while_unfinished_record_survives(self):
        from knowledgeos.autopilot import mark_orphan_if_open, load_state
        api=self.api()
        api.session_start('Interrupted work',session_id='interrupted')
        self.assertTrue(mark_orphan_if_open(self.vault))
        first=api.session_start('Next work',session_id='next')
        self.assertIn('mid-thought',first['soft_prompt'])
        api.session_end(session_id='next')
        second=api.session_start('Another chat',session_id='another')
        self.assertIsNone(second['soft_prompt'])
        self.assertEqual(load_state(self.vault)['sessions']['interrupted']['status'],'orphaned')

    def test_interrupted_summary_can_retry_after_midnight(self):
        import datetime
        from unittest import mock
        from knowledgeos.memory import dispatch
        real_date=datetime.date
        class FirstDay(real_date):
            @classmethod
            def today(cls): return cls(2026,10,19)
        class NextDay(real_date):
            @classmethod
            def today(cls): return cls(2026,10,20)
        api=self.api()
        api.session_start('Work',session_id='midnight')
        arguments={'session_id':'midnight','summary':'A durable summary'}
        with mock.patch('knowledgeos.memory.datetime.date',FirstDay), mock.patch.object(api,'ops_status',side_effect=RuntimeError('Interrupted after capture')):
            first=dispatch(api,'memory_session_end',arguments)
        self.assertIn('error',first)
        with mock.patch('knowledgeos.memory.datetime.date',NextDay):
            retry=dispatch(api,'memory_session_end',arguments)
        self.assertNotIn('error',retry,retry)
        self.assertTrue(retry['captured']['ok'])
        self.assertEqual(len(list((self.vault/'Inbox').glob('capture-*.md'))),1)

if __name__=='__main__': unittest.main()
