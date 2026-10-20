"""Installed host proof refuses mismatched launchers before any model call."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from support import ROOT

SCRIPTS = ROOT/".agents/skills/verify-twinaatma/scripts"


@unittest.skipIf(sys.version_info < (3, 11), "Genuine host driver requires Python 3.11+")
class InstalledHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(SCRIPTS))
        import installed_host
        cls.driver=installed_host

    def test_installed_config_refuses_source_imports_and_substituted_launcher(self):
        installation={"executable":str(ROOT/"candidate/twinaatma.exe"),"vault":str(ROOT/"synthetic-vault")}
        server={"command":installation["executable"],"args":["mcp","--vault",installation["vault"]],"env":{}}
        self.assertTrue(self.driver.server_matches(server,installation))
        self.assertFalse(self.driver.server_matches({**server,"command":sys.executable},installation))
        self.assertFalse(self.driver.server_matches({**server,"env":{"PYTHONPATH":str(ROOT)}},installation))
        self.assertFalse(self.driver.server_matches({**server,"args":["mcp","--vault","other"]},installation))

    def test_stale_artifact_report_stops_before_host_or_model_launch(self):
        base=ROOT/"work/gc-artifacts/.knowledgeos/installed-driver-tests"
        base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as tmp:
            path=Path(tmp);evidence=path/"artifact.json"
            evidence.write_text(json.dumps({"producer":"verify-twinaatma.artifact/v1","producer_sha256":"stale"}),encoding="utf-8")
            result=subprocess.run([sys.executable,"-B",str(SCRIPTS/"installed_host.py"),"--artifact-report",str(evidence),"--output",str(path/"proof"),"--codex","must-not-be-launched"],
                capture_output=True,text=True,encoding="utf-8",timeout=30)
            self.assertEqual(result.returncode,1,result.stderr)
            report=json.loads(next((path/"proof").glob("*/report.json")).read_text(encoding="utf-8"))
            self.assertEqual(report["verdict"],"FAIL")
            self.assertEqual(report["processes"],[])
            self.assertIn("stale",report["error"])
            self.assertEqual(report["cases"],[])
