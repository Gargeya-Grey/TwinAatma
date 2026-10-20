import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock
from support import TempVaultCase, ROOT

class LockRepairTests(TempVaultCase):
    def setUp(self):
        super().setUp()
        self.holders=[]

    def tearDown(self):
        for proc in self.holders:
            self.stop(proc)
        super().tearDown()

    def holder(self, kind):
        code='''import sys\nfrom pathlib import Path\nfrom knowledgeos import gate,indexer\nvault=Path(sys.argv[1])\nlock=gate._lock(vault) if sys.argv[2]=='gate' else indexer._rebuild_lock(vault)\nwith lock:\n print('READY',flush=True)\n sys.stdin.read()\n'''
        proc=subprocess.Popen([sys.executable,'-B','-c',code,str(self.vault),kind],cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy())
        self.holders.append(proc)
        self.assertEqual(proc.stdout.readline().strip(),'READY')
        return proc

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.communicate('',timeout=15)

    def test_live_old_index_writer_keeps_ownership(self):
        from knowledgeos import indexer
        self.holder('index')
        lock=self.vault/indexer.LOCK_REL
        os.utime(lock,(time.time()-2000,time.time()-2000))
        with mock.patch.object(indexer,'LOCK_WAIT_SECONDS',0.2):
            with self.assertRaises(indexer.IndexBusyError):
                indexer.rebuild_index(self.vault)

    def test_live_old_gate_writer_keeps_ownership(self):
        from knowledgeos import gate
        self.holder('gate')
        os.utime(gate._lock_path(self.vault),(time.time()-2000,time.time()-2000))
        with mock.patch.object(gate,'LOCK_WAIT_SECONDS',0.2):
            result=self.api().propose_self_update('Test','heuristics','* A test rule.',mode='append')
        self.assertIn('error',result)
        self.assertTrue(result.get('retryable'))

    def test_killed_index_owner_recovers_without_waiting_for_age(self):
        from knowledgeos import indexer
        proc=self.holder('index')
        proc.kill();proc.communicate(timeout=15)
        with mock.patch.object(indexer,'LOCK_WAIT_SECONDS',0.2):
            self.assertIsInstance(indexer.rebuild_index(self.vault),dict)

    def test_failed_marker_write_does_not_leave_an_unrecoverable_lock(self):
        import errno
        from knowledgeos.locking import file_lock
        target=self.vault/'.knowledgeos/fault.lock'
        original=os.write
        def fail_token(fd,payload):
            if len(payload)>1: raise OSError(errno.ENOSPC,'Injected full disk')
            return original(fd,payload)
        with mock.patch('knowledgeos.locking.os.write',side_effect=fail_token):
            with self.assertRaises(OSError):
                with file_lock(target,timeout=0.1): pass
        with file_lock(target,timeout=0.1):
            self.assertTrue(target.is_file())

    def test_short_marker_writes_are_completed(self):
        from knowledgeos.locking import file_lock
        target=self.vault/'.knowledgeos/short.lock'
        original=os.write
        def short_write(fd,payload):
            return original(fd,payload[:max(1,len(payload)//2)])
        with mock.patch('knowledgeos.locking.os.write',side_effect=short_write):
            with file_lock(target,timeout=0.1):
                import json
                self.assertEqual(json.loads(target.read_bytes())['pid'],os.getpid())
        self.assertFalse(target.exists())

if __name__=='__main__': unittest.main()
