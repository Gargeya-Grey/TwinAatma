"""Run genuine host conversations against a retained, verified installation."""
import argparse
import json
import os
import shutil
from pathlib import Path
import sys
import tomllib

import artifact
import host

ROOT = host.ROOT
PRODUCER = "verify-twinaatma.installed-host/v1"


def server_matches(server, installation):
    return artifact.installed_server_binding(server, installation["executable"], installation["vault"])


def validate_installation(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    if (report.get("producer") != artifact.PRODUCER
            or report.get("producer_sha256") != host.sha(Path(artifact.__file__))
            or report.get("product_hashes") != host.product_hashes()
            or report.get("verdict") != "PASS"
            or any(report.get(k) is not True for k in ["source_bound", "product_unchanged", "artifact_unchanged", "all_started_processes_stopped"])):
        raise ValueError("Installed artifact evidence is stale, failed or incomplete")
    for name, digest in report["transcript_files"].items():
        if Path(name).name != name or host.sha(path.parent/name) != digest:
            raise ValueError("Retained artifact transcript changed: " + name)
    item, installation = report["artifact"], report["installation"]
    candidate = artifact.plain(item["path"])
    if host.sha(candidate) != item["sha256"]:
        raise ValueError("Retained artifact changed")
    if item["kind"] == "wheel":
        artifact.wheel_binding(candidate, host.product_hashes())
        artifact.installed_origin(installation["import_origin"], path.parent/"venv", host.product_hashes())
        if not installation.get("file_hashes"):
            raise ValueError("Installed launcher and package hashes missing")
        for filename, digest in installation["file_hashes"].items():
            if host.sha(artifact.plain(filename)) != digest:
                raise ValueError("Retained installed file changed: " + filename)
    else:
        artifact.binary_binding(candidate, path.parent/"build-manifest.json", host.product_hashes())
    from acceptance import artifact_report
    artifact_report(path, host.product_hashes())
    config = Path(installation["generated_config"])
    server = tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"]["knowledgeos"]
    if not server_matches(server, installation):
        raise ValueError("Generated configuration does not bind the installed executable")
    return report, server


class InstalledHostRun(host.HostRun):
    def __init__(self, base, executable, prepared):
        super().__init__(base, executable)
        self.prepared = prepared.resolve()
        self.server_artifact_bound = False
        self.artifact_evidence = {"report":str(self.prepared), "sha256":host.sha(self.prepared)}
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "KNOWLEDGEOS_VAULT"):
            self.env.pop(key, None)
        self.host["mode"] = "genuine model sessions; exact installed artifact stdio MCP via transparent audit proxy"

    def initialize(self):
        self.prepared_report, self.server = validate_installation(self.prepared)
        installation = self.prepared_report["installation"]
        self.vault = Path(installation["vault"])
        self.env["KNOWLEDGEOS_STATE_DIR"] = installation["state_dir"]
        self.identity = host.sha(self.vault/"People/Self.md")
        self.server_artifact_bound = True
        self.original_config = Path(installation["generated_config"]).read_bytes()
        (self.directory/"generated-config.toml").write_bytes(self.original_config)
        (self.directory/"artifact-reference.json").write_text(json.dumps(self.artifact_evidence,indent=2),encoding="utf-8")
        code, version, error = self.command("host-version", [self.executable,"--version"])
        if code:
            raise RuntimeError("Codex version failed: " + error)
        self.host["version"] = version.strip()

    def regrade(self, original):
        self.replay_requested=True
        old=json.loads(original.read_text(encoding="utf-8"))
        if (old.get("producer")!=PRODUCER or old.get("product_hashes")!=self.sources
                or old.get("product_unchanged") is not True
                or old.get("server_artifact_bound") is not True
                or old.get("artifact_evidence")!=self.artifact_evidence):
            raise ValueError("Retained host observation does not bind this artifact and product")
        if old.get("isolation",{}).get("before")!=old.get("isolation",{}).get("after") or old["isolation"]["before"]!=self.before:
            raise ValueError("Retained host isolation does not match current sentinels")
        if not old.get("processes") or any(p.get("stopped") is not True for p in old["processes"]):
            raise ValueError("Retained host processes lack shutdown proof")
        self.prepared_report,self.server=validate_installation(self.prepared)
        self.vault=Path(self.prepared_report["installation"]["vault"])
        self.identity=next(c for c in old["cases"] if c["id"]=="host.identity_unchanged")["observed"]["before"]
        if not old.get("transcript_files"):
            raise ValueError("Retained host transcripts missing")
        for name,digest in old["transcript_files"].items():
            path=original.parent/name
            if Path(name).name!=name or path.is_symlink() or host.sha(path)!=digest:
                raise ValueError("Retained host transcript changed: "+name)
            shutil.copy2(path,self.directory/name)
        self.server_artifact_bound=True
        self.host={**old["host"],"mode":old["host"]["mode"]+"; retained observations regraded, no new live trial"}
        self.processes=old["processes"]
        self.replayed_from={"report":str(original),"sha256":host.sha(original),"original_producer_sha256":old.get("producer_sha256"),"original_support_sha256":old.get("support_sha256")}
        self.grade([host.observe_chat(self.directory,label) for label in ["capture","recall","parallel"]])

    def finish(self, error=None):
        if not getattr(self,"replay_requested",False):
            self.processes.extend(host.collect_shutdown(self.directory.glob("*.wire.jsonl")))
        try:
            validate_installation(self.prepared)
            unchanged = host.sha(self.prepared)==self.artifact_evidence["sha256"]
        except (OSError, ValueError, KeyError) as exc:
            unchanged = False
            error = error or str(exc)
        after = {str(p):host.sha(p) for p in self.protected}
        transcript_files = {p.name:host.sha(p) for p in self.directory.iterdir() if p.is_file() and p.name!="report.json"}
        report = {"producer":PRODUCER,"producer_sha256":host.sha(__file__),
            "support_sha256":{"host.py":host.sha(host.__file__),"artifact.py":host.sha(artifact.__file__)},
            "product_hashes":self.sources,"product_unchanged":self.sources==host.product_hashes(),
            "server_artifact_bound":self.server_artifact_bound and unchanged,"artifact_evidence":self.artifact_evidence,
            "host":self.host,"replayed_from":getattr(self,"replayed_from",None),"cases":self.cases,"processes":self.processes,"transcript_files":transcript_files,
            "isolation":{"before":self.before,"after":after},"error":error,
            "limits":["Installed artifact on this platform through Codex CLI; not desktop, other hosts, older runtimes, clean-device restore or owner approval.","Three genuine conversations with shared synthetic vault and two concurrent sessions; not a quality corpus or performance acceptance."]}
        report["verdict"] = "PASS" if (not error and len(self.cases)==10 and all(c["verdict"]=="PASS" for c in self.cases)
            and self.before==after and report["product_unchanged"] and report["server_artifact_bound"]
            and all(p["stopped"] for p in self.processes)) else "FAIL"
        path=self.directory/"report.json"
        path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        from acceptance import snapshot
        try:
            coverage=snapshot([], [path])
        except (ValueError, OSError, KeyError) as exc:
            coverage=snapshot([], [])
            coverage["unusable_host_report"]=str(exc)
            report["verdict"]="FAIL";report["acceptance_error"]=str(exc)
            path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
        (self.directory/"acceptance.json").write_text(json.dumps(coverage,indent=2),encoding="utf-8")
        print(f"Run-only ideal coverage: {coverage['counts']['PASS']}/54; unresolved {coverage['unresolved_percent']:.2f}%")
        print("Evidence:",self.directory,flush=True)
        return 0 if report["verdict"]=="PASS" else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-report",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--codex",default="codex")
    parser.add_argument("--replay",type=Path,help="Regrade unchanged installed-host observations without new model calls")
    args=parser.parse_args()
    base=args.output.resolve()
    relative=base.relative_to((ROOT/"work/gc-artifacts").resolve())
    if ".knowledgeos" not in relative.parts:
        parser.error("Output must contain .knowledgeos beneath work/gc-artifacts")
    run=InstalledHostRun(base,args.codex,args.artifact_report)
    error=None
    try:
        if args.replay:
            run.regrade(args.replay.resolve())
        else:
            run.initialize();run.drive()
    except Exception as exc:
        error=f"{type(exc).__name__}: {exc}"
        print(error,file=sys.stderr)
    return run.finish(error)


if __name__=="__main__":
    raise SystemExit(main())
