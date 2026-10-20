"""Literal graders and transparent wire transport used by real-host acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from support import ROOT

SCRIPT=ROOT/".agents/skills/verify-twinaatma/scripts/host.py"
spec=importlib.util.spec_from_file_location("host_acceptance",SCRIPT)
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)

class HostDriverTests(unittest.TestCase):
    def test_fact_grader_rejects_conflicting_and_unsupported_weights(self):
        self.assertTrue(host.supported_fact("Your limit is 7 kg. Source: Inbox/packing.md"))
        self.assertFalse(host.supported_fact("Your limit is 9 kg; it used to be 7 kg."))
        self.assertFalse(host.supported_fact("I don't know the limit."))

    def test_abstention_is_about_the_unsupported_fact(self):
        self.assertTrue(host.unknown_shoe("I don't know your shoe size."))
        self.assertTrue(host.unknown_shoe("Shoe size: unknown; no record is available."))
        self.assertFalse(host.unknown_shoe("I don't know the trip date. Your shoe size is 42."))
        self.assertFalse(host.unknown_shoe("Your shoe size is 42, but I don't know for sure."))

    def test_grader_rejects_negation_and_later_contradictions(self):
        self.assertFalse(host.supported_fact("Seaglass is not limited to 7 kg."))
        self.assertFalse(host.unknown_shoe("Your shoe size is unknown. Your shoe size is 42."))

    def test_lookup_plan_is_not_a_personal_fact_or_an_unknown_answer(self):
        plan="I'll check your stored notes for the luggage limit and shoe size."
        self.assertTrue(host.unknown_shoe(plan+"\nI do not know your shoe size; I found no stored evidence."))
        self.assertFalse(host.unknown_shoe(plan))
        self.assertFalse(host.unknown_shoe("I'll check notes, but your shoe size is 42. Your shoe size is unknown."))

    def test_unknown_cannot_be_followed_by_numeric_or_verbal_personal_claim(self):
        self.assertFalse(host.unknown_shoe("I don't know your shoe size. It is 42."))
        self.assertFalse(host.unknown_shoe("I do not know your shoe size, but it is forty two."))
        self.assertFalse(host.unknown_shoe("Your shoe size is unknown and it is XL."))

    def test_source_binding_rejects_unknown_installed_launchers(self):
        vault=ROOT/"synthetic-vault"
        server={"command":sys.executable,"args":["-P","-m","knowledgeos","mcp","--vault",str(vault)],"env":{"PYTHONPATH":str(ROOT)}}
        self.assertTrue(host.source_binding(server,vault))
        self.assertFalse(host.source_binding({**server,"command":"old-twinaatma.exe"},vault))
        self.assertFalse(host.source_binding({**server,"env":{"PYTHONPATH":"other-checkout"}},vault))

    def test_successful_session_requires_exact_returned_id(self):
        start={"name":"memory_session_start","ok":True,"arguments":{},"payload":{"session_id":"alpha"}}
        end={"name":"memory_session_end","ok":True,"arguments":{"session_id":"beta"},"payload":{"session_id":"beta"}}
        self.assertIsNone(host.session_pair([start,end]))
        end["arguments"]["session_id"]=end["payload"]["session_id"]="alpha"
        self.assertEqual(host.session_pair([start,end])[0],"alpha")
        end["ok"]=False
        self.assertIsNone(host.session_pair([start,end]))

    def test_proxy_launches_original_command_and_preserves_protocol_bytes(self):
        with tempfile.TemporaryDirectory(prefix="ta-host-wire-") as tmp:
            root=Path(tmp);server=root/"server.py";log=root/"wire.jsonl"
            server.write_text("import sys,json\nfor line in sys.stdin:\n value=json.loads(line); print(json.dumps({'jsonrpc':'2.0','id':value['id'],'result':{'content':[{'type':'text','text':'{\\\"ok\\\": true}'}]}}),flush=True)\n",encoding="utf-8")
            # The protocol peer is real and bounded; no model or authentication.
            request={"jsonrpc":"2.0","id":17,"method":"tools/call","params":{"name":"memory_capture","arguments":{"title":"A"}}}
            process=subprocess.run([sys.executable,"-B",str(SCRIPT),"--proxy",str(log),"--",sys.executable,"-B",str(server)],
                input=json.dumps(request)+"\n",capture_output=True,text=True,encoding="utf-8",timeout=30)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertEqual(json.loads(process.stdout)["id"],17)
            records=host.rows(log)
            self.assertEqual(records[0]["command"],[sys.executable,"-B",str(server)])
            self.assertEqual(records[-1]["kind"],"exit")
            calls=host.calls_from_wire(records)
            self.assertEqual(calls[0]["payload"],{"ok":True})
            self.assertTrue(calls[0]["ok"])

    def test_shutdown_collection_waits_for_wire_writer_and_retains_final_exit(self):
        with tempfile.TemporaryDirectory(prefix="ta-host-shutdown-") as tmp:
            root=Path(tmp);server=root/"server.py";log=root/"wire.jsonl"
            server.write_text("import sys,time\nfor line in sys.stdin: pass\ntime.sleep(.35)\nsys.exit(7)\n",encoding="utf-8")
            process=subprocess.Popen([sys.executable,"-B",str(SCRIPT),"--proxy",str(log),"--",sys.executable,"-B",str(server)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            waiter=None
            try:
                deadline=time.monotonic()+10
                while not log.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(log.exists(),"Real wire proxy did not start")
                initial=host.rows(log)
                self.assertEqual(initial[0]["kind"],"process")
                self.assertFalse(any(r.get("kind")=="exit" for r in initial))
                process.stdin.close()
                waiter=threading.Thread(target=process.wait);waiter.start()
                observed=host.collect_shutdown([log],timeout=10)
                self.assertEqual([(p["role"],p["stopped"],p["exit_code"]) for p in observed],
                    [("pid",True,7),("proxy_pid",True,None)])
                self.assertEqual(host.rows(log)[-1]["kind"],"exit")
            finally:
                if process.poll() is None:process.kill()
                process.wait(timeout=10)
                if waiter:waiter.join(timeout=10)
                process.stdout.close();process.stderr.close()

    def test_shutdown_deadline_preserves_live_or_unknown_process_as_unstopped(self):
        with tempfile.TemporaryDirectory(prefix="ta-host-live-") as tmp:
            log=Path(tmp)/"wire.jsonl"
            process=subprocess.Popen([sys.executable,"-B","-c","import time; time.sleep(30)"])
            try:
                log.write_text(json.dumps({"kind":"process","pid":process.pid,"proxy_pid":0})+"\n",encoding="utf-8")
                observed=host.collect_shutdown([log],timeout=.1)
                self.assertEqual([(p["role"],p["stopped"],p["exit_code"]) for p in observed],
                    [("pid",False,None),("proxy_pid",False,None)])
                self.assertIsNone(process.poll())
            finally:
                process.terminate();process.wait(timeout=10)

if __name__=="__main__":unittest.main()
