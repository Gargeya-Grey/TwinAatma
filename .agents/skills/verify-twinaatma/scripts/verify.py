"""Verify source CLI/MCP behavior in a retained, isolated synthetic vault."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[4]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def manifest():
    paths = [*ROOT.glob("knowledgeos/*.py"), *ROOT.glob("tests/*.py"),
             *ROOT.glob("tests/spec/*.py"), *ROOT.glob(".cursor/hooks/*.py"),
             *Path(__file__).parent.parent.rglob("*")]
    paths += [ROOT / n for n in ("AGENTS.md", "README.md", "pyproject.toml", "setup.py")]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(paths)) if p.is_file()}


class Run:
    def __init__(self, base):
        self.directory = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.vault = self.directory / "vault"
        self.env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(self.directory / "gate-state"),
                        KNOWLEDGEOS_VAULT=str(self.vault), PYTHONDONTWRITEBYTECODE="1",
                        PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8")
        self.checks, self.processes = [], []
        self.session_id = None
        self.transcript_lock = threading.Lock()

    def record(self, kind, value):
        with self.transcript_lock:
            with (self.directory / "transcript.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(kind=kind, **value), ensure_ascii=False) + "\n")

    def command(self, *arguments, stdin_text="", vault=None):
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", *arguments]
        env = self.env if vault is None else dict(self.env, KNOWLEDGEOS_VAULT=str(vault))
        result = subprocess.run(command, cwd=self.directory, env=env,
                                input=stdin_text, capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.record("cli", dict(command=command, vault=env["KNOWLEDGEOS_VAULT"], exit_code=result.returncode,
                                stdout=result.stdout, stderr=result.stderr))
        return result

    def rpc(self, calls):
        messages = [dict(jsonrpc="2.0", id=1, method="initialize", params={
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "verify-twinaatma", "version": "1"}}),
            dict(jsonrpc="2.0", method="notifications/initialized")]
        for index, (name, arguments) in enumerate(calls, 2):
            arguments = dict(arguments)
            if name == "memory_session_end" and "session_id" not in arguments and self.session_id:
                arguments["session_id"] = self.session_id
            messages.append(dict(jsonrpc="2.0", id=index, method="tools/call",
                                 params=dict(name=name, arguments=arguments)))
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp",
                   "--vault", str(self.vault), "--framing", "ndjson"]
        process = subprocess.Popen(command, cwd=self.directory, env=self.env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8")
        tracked = dict(pid=process.pid, stopped=False)
        self.processes.append(tracked)
        try:
            stdout, stderr = process.communicate(
                "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages), timeout=90)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        finally:
            tracked["stopped"] = process.poll() is not None
            tracked["exit_code"] = process.returncode
        self.record("mcp", dict(command=command, pid=process.pid, requests=messages,
                                stdout=stdout, stderr=stderr, exit_code=process.returncode))
        if process.returncode:
            raise RuntimeError(f"MCP exited {process.returncode}: {stderr}")
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        by_id = {item["id"]: item for item in responses}
        if len(responses) != len(calls) + 1 or by_id[1]["result"]["serverInfo"]["name"] != "knowledgeos-memory":
            raise RuntimeError("Wrong MCP response count or server identity")
        results = [dict(payload=json.loads(by_id[i]["result"]["content"][0]["text"]),
                        is_error=by_id[i]["result"].get("isError", False))
                   for i in range(2, len(calls) + 2)]
        for (name, _), result in zip(calls, results):
            if name in ("memory_session_start", "memory_breathe") and result["payload"].get("session_id"):
                self.session_id = result["payload"]["session_id"]
        return results

    def tool(self, name, **arguments):
        return self.rpc([(name, arguments)])[0]["payload"]

    def check(self, identifier, condition, observed):
        item = dict(id=identifier, verdict="PASS" if condition else "FAIL", observed=observed)
        self.checks.append(item)
        print(f"{item['verdict']} {identifier}", flush=True)

    def initialize(self):
        result = self.command("init", str(self.vault), "--name", "Verification fixture", "--non-interactive")
        if result.returncode or not (self.vault / "People/Self.md").is_file():
            raise RuntimeError("Fresh vault initialization failed; inspect transcript")
        initialized = json.loads(result.stdout)
        post = initialized.get("post_init", {})
        self.check("setup.cli_init", {"rebuild", "validate"}.issubset(post) and all(v.get("ok", False) for v in post.values()), initialized)
        doctor = self.command("doctor", "--vault", str(self.vault))
        self.check("setup.doctor", doctor.returncode == 0, doctor.stdout)
        if doctor.returncode:
            raise RuntimeError("Doctor failed; fixture is not ready")
        self.identity_before = digest(self.vault / "People/Self.md")

    def core(self):
        marker = "verifyquartz" + uuid.uuid4().hex[:10]
        start, capture = self.rpc([
            ("memory_session_start", dict(task_hint=marker)),
            ("memory_capture", dict(title="Verification fact", content=f"The launch code is {marker}."))])
        self.check("memory.context_loaded", bool(start["payload"].get("context")), start)
        saved = capture["payload"]
        path = self.vault / saved["path"]
        self.check("memory.capture_persisted", saved.get("ok") is True and marker in path.read_text(encoding="utf-8"), saved)
        search, note = self.rpc([
            ("memory_search", dict(query=marker)),
            ("memory_get_note", dict(path_or_id=saved["path"]))])
        self.check("memory.recall_after_restart", any(h.get("path") == saved["path"] for h in search["payload"].get("ranked", [])), search)
        self.check("memory.quote_matches_file", note["payload"].get("body", "").strip() == path.read_text(encoding="utf-8").split("---", 2)[2].strip() and note["payload"].get("path") == saved["path"], note)
        proposal = self.tool("memory_propose_self_update", summary="Synthetic verification preference",
                             section="heuristics", proposed_markdown="* Prefer the verification marker.", mode="append")
        proposal_file = self.vault / proposal["proposal_path"]
        self.check("identity.proposal_persisted", proposal_file.is_file() and "\nstatus: draft\n" in proposal_file.read_text(encoding="utf-8"), proposal)
        refused = self.rpc([("memory_accept_self_update", dict(proposal_path=proposal["proposal_path"]))])[0]
        self.check("identity.tool_refuses", refused["is_error"] and bool(refused["payload"].get("error")), refused)
        rejected = self.tool("memory_reject_self_update", proposal_path=proposal["proposal_path"], reason="Verification fixture only")
        remaining = self.tool("memory_list_self_proposals")
        persisted = "\nstatus: rejected\n" in proposal_file.read_text(encoding="utf-8")
        self.check("identity.rejection_recorded", rejected.get("ok") is True and persisted
                   and not any(p.get("path") == proposal["proposal_path"] for p in remaining.get("open", [])),
                   dict(response=rejected, persisted_status_rejected=persisted, fresh_listing=remaining))
        self.check("identity.bytes_unchanged", digest(self.vault / "People/Self.md") == self.identity_before,
                   dict(before=self.identity_before, after=digest(self.vault / "People/Self.md")))
        changed = marker + "updated"
        path.write_text(path.read_text(encoding="utf-8").replace(marker, changed), encoding="utf-8", newline="")
        current, old = self.tool("memory_search", query=changed), self.tool("memory_search", query=marker)
        self.check("freshness.edited_note", any(h.get("path") == saved["path"] for h in current.get("ranked", []))
                   and not old.get("ranked"), dict(current=current, old=old))
        path.rename(self.directory / "removed-note.md")
        absent = self.tool("memory_search", query=changed)
        self.check("freshness.removed_note", not absent.get("ranked"), absent)
        ended = self.tool("memory_session_end", summary=f"Verified launch code {marker}.", capture_title="Verification session")
        recalled = self.tool("memory_search", query=marker)
        self.check("memory.session_summary_recalled", bool(ended.get("captured", {}).get("ok"))
                   and bool(recalled.get("ranked")), dict(ended=ended, recalled=recalled))
        self.setup_configurations()
        self.setup_post_init_failure()

    def setup_configurations(self):
        import tomllib

        observations = []
        for host, folder, key in (("cursor", ".cursor", "mcpServers"),
                                  ("vscode", ".vscode", "servers"),
                                  ("codex", ".codex", "mcp_servers")):
            vault = self.directory / "setup cases" / (host + " valid vault")
            target = vault / folder / ("config.toml" if host == "codex" else "mcp.json")
            target.parent.mkdir(parents=True)
            foreign = dict(command="foreign-command", args=["foreign argument"])
            custom = dict(custom_setting="keep setting", env={"CUSTOM_FLAG": "keep env"})
            owned = dict(command="old-command", args=["obsolete argument"], **custom)
            if host == "codex":
                prefix = '# Keep this user comment.\nmodel = "configured-model"\n\n[mcp_servers.foreign]\ncommand = "foreign-command"\nargs = ["foreign argument"]\n\n'
                original = prefix + '[mcp_servers.knowledgeos]\ncommand = "old-command"\nargs = ["obsolete argument"]\ncustom_setting = "keep setting"\n\n[mcp_servers.knowledgeos.env]\nCUSTOM_FLAG = "keep env"\n'
                parse = tomllib.loads
            else:
                original = json.dumps({"user_setting": {"theme": "keep theme"},
                                       key: {"foreign": foreign, "knowledgeos": owned}}, indent=2) + "\n"
                parse = json.loads
            target.write_bytes(original.encode("utf-8"))
            first = self.command("setup-host", "--host", host, "--vault", str(vault), "--write", vault=vault)
            merged_bytes = target.read_bytes()
            merged = parse(merged_bytes.decode("utf-8"))
            server = merged[key]["knowledgeos"]
            second = self.command("setup-host", "--host", host, "--vault", str(vault), "--write", vault=vault)
            foreign_ok = (merged.get("model") == "configured-model" and merged_bytes.startswith(prefix.encode("utf-8"))
                          if host == "codex" else merged.get("user_setting") == {"theme": "keep theme"})
            launcher = Path(server.get("command", ""))
            passed = (first.returncode == second.returncode == 0 and foreign_ok
                      and merged[key]["foreign"] == foreign and server.get("custom_setting") == "keep setting"
                      and server.get("env", {}).get("CUSTOM_FLAG") == "keep env"
                      and server.get("env", {}).get("KNOWLEDGEOS_VAULT") == str(vault)
                      and server.get("cwd") == str(vault) and launcher.is_absolute() and launcher.is_file()
                      and server.get("args", [])[-3:] == ["mcp", "--vault", str(vault)]
                      and target.read_bytes() == merged_bytes)
            observations.append(dict(host=host, case="valid merge and repeat", passed=passed,
                                     original_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
                                     merged_sha256=hashlib.sha256(merged_bytes).hexdigest(),
                                     repeated_sha256=digest(target), first_exit=first.returncode,
                                     repeat_exit=second.returncode, merged=merged))
            if host == "codex":
                invalid = [("malformed", b"mcp_servers = ["),
                           ("wrong servers shape", b"mcp_servers = []\n"),
                           ("wrong owned shape", b'[mcp_servers]\nknowledgeos = "invalid"\n'),
                           ("wrong env shape", b"[mcp_servers.knowledgeos]\nenv = []\n"),
                           ("nonstring env", b"[mcp_servers.knowledgeos.env]\nCUSTOM_FLAG = 2\n")]
            else:
                invalid = [("malformed", b'{"unfinished":'), ("wrong root shape", b"[]"),
                           ("wrong servers shape", json.dumps({key: []}).encode("utf-8")),
                           ("wrong owned shape", json.dumps({key: {"knowledgeos": []}}).encode("utf-8")),
                           ("wrong env shape", json.dumps({key: {"knowledgeos": {"env": []}}}).encode("utf-8"))]
            for name, content in [*invalid, ("invalid utf8", b"\xff")]:
                target.write_bytes(content)
                result = self.command("setup-host", "--host", host, "--vault", str(vault), "--write", vault=vault)
                passed = (result.returncode != 0 and target.read_bytes() == content
                          and "preserved" in result.stderr.lower() and str(target) in result.stderr)
                observations.append(dict(host=host, case=name, passed=passed, exit_code=result.returncode,
                                         before_sha256=hashlib.sha256(content).hexdigest(),
                                         after_sha256=digest(target), diagnostic=result.stderr))
        self.check("setup.config_preserved", all(case["passed"] for case in observations), observations)

    def setup_post_init_failure(self):
        vault = self.directory / "setup cases" / "post init obstruction vault"
        vault.mkdir(parents=True)
        obstruction = vault / ".knowledgeos"
        content = b"Retain this existing obstruction.\n"
        obstruction.write_bytes(content)
        result = self.command("init", str(vault), "--name", "Partial setup fixture", "--non-interactive", "--force", vault=vault)
        partial = json.loads(result.stdout) if result.stdout.strip() else {}
        rebuild = partial.get("post_init", {}).get("rebuild", {})
        preserved = obstruction.read_bytes() == content
        self.check("setup.post_init_failure", result.returncode != 0 and partial.get("ok") is False
                   and rebuild.get("ok") is False and bool(rebuild.get("error"))
                   and (vault / "People/Self.md").is_file() and preserved and bool(partial.get("next_steps")),
                   dict(exit_code=result.returncode, report=partial, obstruction_preserved=preserved,
                        obstruction_sha256=digest(obstruction), partial_self_exists=(vault / "People/Self.md").is_file()))

    def failure(self):
        self.tool("memory_session_start", task_hint="Verify interruption handling")
        proposal = self.tool("memory_propose_self_update", summary="Synthetic prompt verification",
                             section="heuristics", proposed_markdown="* Prefer explicit evidence.", mode="append")
        if "proposal_path" not in proposal:
            raise RuntimeError(f"Could not create prompt precondition: {proposal}")
        started = self.tool("memory_session_start", task_hint="Continue verification")
        ended = self.tool("memory_session_end", summary="Completed prompt check.")
        if not started.get("soft_prompt"):
            raise RuntimeError("Prompt-once precondition failed; no prompt was issued")
        self.check("experience.prompt_once", not ended.get("soft_prompt"),
                   dict(start_prompt=started.get("soft_prompt"), end_prompt=ended.get("soft_prompt")))
        self.tool("memory_session_start", task_hint="Verify failed capture preservation")
        inbox = self.vault / "Inbox"
        inbox.rename(self.directory / "retained-inbox")
        inbox.write_text("Synthetic filesystem obstruction", encoding="utf-8")
        try:
            result = self.rpc([("memory_session_end", dict(summary="This summary must survive or stay pending."))])[0]
            state = json.loads((self.vault / ".knowledgeos/autopilot.json").read_text(encoding="utf-8"))
            failed = bool(result["payload"].get("captured", {}).get("error"))
            self.check("recovery.failed_summary_stays_pending", failed and result["is_error"]
                       and not state.get("session_ended"), dict(response=result, state=state))
        finally:
            inbox.rename(self.directory / "obstruction.txt")
            (self.directory / "retained-inbox").rename(inbox)
        first = self.tool("memory_session_end", summary="This summary must survive or stay pending.")
        retry = self.tool("memory_session_end", summary="This summary must survive or stay pending.")
        self.check("recovery.restored_summary_saved_once", first.get("captured", {}).get("ok") is True
                   and first == retry and len(list(inbox.glob("capture-*.md"))) == 2,
                   dict(first=first, retry=retry))

    def concurrency(self):
        a, b = "verify-chat-a", "verify-chat-b"
        for sid in (a, b, a):
            self.tool("memory_session_start", task_hint=sid, session_id=sid)
        first = self.tool("memory_session_end", session_id=a, summary="Alpha work completed.")
        retry = self.tool("memory_session_end", session_id=a, summary="Alpha work completed.")
        state = json.loads((self.vault / ".knowledgeos/autopilot.json").read_text(encoding="utf-8"))
        self.check("session.concurrent_chats_independent", state["real_sessions"] == 2
                   and state["sessions_completed"] == 1 and state["sessions"][a]["status"] == "ended"
                   and state["sessions"][b]["status"] == "open", state)
        self.check("session.end_retry_idempotent", first == retry and first.get("captured", {}).get("ok") is True, retry)
        conflict = self.rpc([("memory_session_end", dict(session_id=a, summary="Different content."))])[0]
        self.check("session.conflicting_retry_refused", conflict["is_error"] and bool(conflict["payload"].get("error")), conflict)
        hook = self.command("hook", "twin_session_end", "--vault", str(self.vault),
                            stdin_text=json.dumps({"memory_session_id": b}))
        state = json.loads((self.vault / ".knowledgeos/autopilot.json").read_text(encoding="utf-8"))
        self.check("recovery.hook_leaves_only_interrupted_chat", hook.returncode == 0
                   and state["sessions"][a]["status"] == "ended"
                   and state["sessions"][b]["status"] == "orphaned", state)
        resumed = self.tool("memory_session_start", session_id="verify-chat-c", task_hint="Resume work")
        self.tool("memory_session_end", session_id="verify-chat-c")
        later = self.tool("memory_session_start", session_id="verify-chat-d", task_hint="New work")
        self.check("experience.orphan_prompt_once", bool(resumed.get("soft_prompt"))
                   and not later.get("soft_prompt"), dict(first=resumed, later=later))
        marker = "capturequartz" + uuid.uuid4().hex[:10]
        def capture(index):
            return self.tool("memory_capture", title="Concurrent capture", content=f"{marker} body {index}.")
        with ThreadPoolExecutor(max_workers=20) as executor:
            receipts = list(executor.map(capture, range(20)))
        complete = all(r.get("ok") and f"{marker} body {i}." in (self.vault / r["path"]).read_text(encoding="utf-8")
                       for i, r in enumerate(receipts))
        self.check("recovery.twenty_capture_writers", complete and len({r.get("path") for r in receipts}) == 20, receipts)
        recalled = self.tool("memory_search", query=marker, limit=40)
        self.check("memory.concurrent_bodies_recalled", len(recalled.get("ranked", [])) == 20, recalled)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journey", choices=("core", "failure", "concurrency"), default="core")
    parser.add_argument("--output", type=Path, required=True, help="Run parent under work/gc-artifacts")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Source verification needs Python 3.11+ for -P; package compatibility is a separate gate")
    base = args.output.resolve()
    relative = base.relative_to((ROOT / "work/gc-artifacts").resolve())
    if ".knowledgeos" not in relative.parts:
        parser.error("Output must include a .knowledgeos directory so synthetic notes stay out of real memory")
    run = Run(base)
    sources = manifest()
    protected = {n: digest(ROOT / n) for n in ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json")}
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    report = dict(journey=args.journey, scope="Source CLI/MCP with a synthetic vault; not real-host acceptance",
                  source_revision=head.stdout.strip(), dirty_tree=status.stdout, source_hashes=sources,
                  python=sys.version, directory=str(run.directory), checks=run.checks)
    try:
        run.initialize()
        getattr(run, args.journey)()
    except Exception as exc:
        run.check("harness.execution", False, f"{type(exc).__name__}: {exc}")
    finally:
        run.check("isolation.real_vault_sentinels_unchanged", protected == {n: digest(ROOT / n) for n in protected}, protected)
        run.check("evidence.source_unchanged", sources == manifest(), "Compared source fingerprints before and after")
        report["processes"] = run.processes
        report["all_started_mcp_processes_stopped"] = all(p["stopped"] for p in run.processes)
        report["verdict"] = "FAIL" if any(c["verdict"] != "PASS" for c in run.checks) else "PASS"
        report["ideal_system_verdict"] = "NOT CHECKED"
        report["retention"] = "Fixture, gate state, and evidence retained. No automatic collection."
        report_path = run.directory / "report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        from acceptance import snapshot
        try:
            coverage = snapshot([report_path], [])
            (run.directory / "acceptance.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
            print(f"Run-only ideal coverage: {coverage['counts']['PASS']}/54; unresolved {coverage['unresolved_percent']:.2f}% (combine reports for progress)")
        except ValueError as exc:
            (run.directory / "acceptance-error.txt").write_text(str(exc), encoding="utf-8")
            report["verdict"] = "FAIL"
            report["acceptance_error"] = str(exc)
            report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Evidence: {run.directory}")
    return 1 if report["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
