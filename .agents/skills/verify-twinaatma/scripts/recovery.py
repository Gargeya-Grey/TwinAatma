"""Observe index degradation and real lock ownership through isolated public processes."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import time

from data_preservation import DataRun, ROOT, inventory, sha, source_files

INDEX_CASES = ("missing_index", "corrupt_index", "busy_sqlite", "busy_rebuild", "blocked_rebuild", "blocked_manifest")
LOCK_KINDS = ("index", "gate", "sessions")
LOCK_SCENARIOS = ("live_old_owner", "dead_owner", "replacement_marker", "blocked_marker", "blocked_guard")
JOURNEYS = {
    "index": {"producer": "verify-twinaatma.recovery-index/v1", "outcome": "RECOVERY.index_degradation", "cases": INDEX_CASES},
    "locks": {"producer": "verify-twinaatma.recovery-locks/v1", "outcome": "RECOVERY.ownership_locks",
              "cases": tuple(kind + "_" + scenario for kind in LOCK_KINDS for scenario in LOCK_SCENARIOS)},
    "write-faults": {"producer": "verify-twinaatma.recovery-write-faults/v1", "outcome": "RECOVERY.ownership_locks",
                     "cases": tuple(kind + "_partial_marker_write" for kind in LOCK_KINDS)},
}
QUERY = "rq731quote"
ORIGINAL_QUOTE = "rq731quote evidence before the editor changes it."
CURRENT_QUOTE = "rq731quote current evidence after an external edit."
FRESH_QUOTE = "rq731quote new evidence created while indexing is unavailable."
REPLACEMENT = b'{"pid":1,"nonce":"unrelated-replacement-owner-rq731"}'
OBSTRUCTION = b"UNRELATED OWNERSHIP RQ731\x00\xff\n"


def note(title, body, identifier):
    return ("---\ntype: concept\ntitle: " + title + "\ndescription: Synthetic recovery acceptance note\nstatus: active\n"
            "schema: knowledgeos-v0.3\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [rq731, synthetic]\nid: kos:concept:"
            + identifier + "\n---\n# " + title + "\n" + body + "\n").encode()


def rows_from(payload):
    return [row for key, value in payload.items() if isinstance(value, list) for row in value if isinstance(row, dict) and "path" in row]


def scope_inventory(directory):
    try:
        return inventory(directory)
    except OSError:
        result = {}
        def visit(path):
            for entry in sorted(os.scandir(path), key=lambda member: member.name):
                member = Path(entry.path)
                relative = member.relative_to(directory).as_posix()
                info = member.lstat()
                linked = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
                if linked:
                    result[relative] = {"kind": "link", "target": os.readlink(member)}
                elif stat.S_ISDIR(info.st_mode):
                    result[relative] = {"kind": "directory"}
                    visit(member)
                elif stat.S_ISREG(info.st_mode):
                    row = {"kind": "file", "size": info.st_size, "links": info.st_nlink}
                    try:
                        row["sha256"] = sha(member)
                    except OSError as error:
                        cache = relative in {"vault/knowledge_index.db" + suffix for suffix in ("", "-wal", "-shm", "-journal")}
                        guard = relative in {"vault/.knowledgeos/index-rebuild.lock.guard", "vault/.knowledgeos/sessions.lock.guard"}
                        parts = Path(relative).parts
                        guard = guard or len(parts) == 4 and parts[:2] == ("gate-state", "vaults") and parts[-1] == "self-gate.lock.guard"
                        if not cache and not guard:
                            raise
                        row.update(sha256=None, observation_error=type(error).__name__ + ": " + str(error),
                                   limitation="Windows native byte-range lock prevented a raw cache/guard read; all source files are still hashed")
                    result[relative] = row
                else:
                    result[relative] = {"kind": "other", "mode": info.st_mode}
        visit(Path(directory))
        return result


def search_observation(result, frozen, require_fresh=False):
    payload = result.get("payload") if isinstance(result, dict) else None
    if not isinstance(payload, dict):
        return {"valid": False, "reason": "Missing public search object", "result": result}
    rows = rows_from(payload)
    quotes = [str(row.get("snippet", "")) for row in rows if row.get("path") == "Concepts/Recovery.md"]
    paths = sorted({row.get("path") for row in rows})
    disclosure = payload.get("index_frozen") is True and isinstance(payload.get("index_frozen_note"), str) and bool(payload["index_frozen_note"].strip())
    current = bool(quotes) and any(CURRENT_QUOTE in quote for quote in quotes) and all(ORIGINAL_QUOTE not in quote for quote in quotes)
    fresh = "Concepts/Fresh.md" in paths and any(FRESH_QUOTE in str(row.get("snippet", "")) for row in rows if row.get("path") == "Concepts/Fresh.md")
    valid = result.get("is_error") is False and current and "Concepts/Removed.md" not in paths
    valid = valid and (disclosure if frozen else not payload.get("index_frozen")) and (fresh if require_fresh else True)
    return {"valid": valid, "is_error": result.get("is_error"), "current_quote": current, "new_note_recalled": fresh,
            "deleted_note_absent": "Concepts/Removed.md" not in paths, "incompleteness_disclosed": disclosure,
            "observed_paths": paths, "quotes": quotes, "payload": payload}


def public_success(result, kind):
    payload = result.get("payload") if isinstance(result, dict) else None
    if not isinstance(payload, dict) or result.get("is_error") is not False:
        return False
    if kind == "gate":
        return payload.get("policy") == "proposal_only" and payload.get("mutated_self") is False and bool(payload.get("proposal_path"))
    if kind == "sessions":
        return payload.get("session_id") == "rq731-ownership-session" and isinstance(payload.get("context"), dict)
    return False


def refused(action):
    if "command" in action:
        command = action["command"]
        return (action.get("success") is False and command.get("error") is None and command.get("stopped") is True
                and isinstance(command.get("exit_code"), int) and command["exit_code"] != 0 and bool(action.get("stderr", "").strip()))
    result = action.get("result", {})
    return result.get("is_error") is True and isinstance(result.get("payload", {}).get("error"), str) and bool(result["payload"]["error"].strip())


HOLDER_CODE = '''import contextlib,json,os,sqlite3,sys,time
from pathlib import Path
from knowledgeos import gate,indexer
from knowledgeos.autopilot import state_lock
vault=Path(sys.argv[1]);kind=sys.argv[2]
if kind=='sqlite':
 conn=sqlite3.connect(vault/'knowledge_index.db',timeout=2)
 conn.execute('BEGIN IMMEDIATE')
 manager=contextlib.nullcontext()
 path=vault/'knowledge_index.db'
 threshold=None
elif kind=='index':
 manager=indexer._rebuild_lock(vault);path=vault/indexer.LOCK_REL;threshold=indexer.LOCK_STALE_SECONDS
elif kind=='gate':
 manager=gate._lock(vault);path=gate._lock_path(vault);threshold=gate.LOCK_STALE_SECONDS
else:
 manager=state_lock(vault);path=vault/'.knowledgeos/sessions.lock';threshold=None
with manager:
 print(json.dumps({'ready':True,'pid':os.getpid(),'kind':kind,'path':str(path),'stale_threshold_seconds':threshold,'token':path.read_bytes().hex() if kind!='sqlite' else None}),flush=True)
 sys.stdin.read()
if kind=='sqlite': conn.rollback();conn.close()
'''


class RecoveryRun(DataRun):
    def __init__(self, output, journey):
        super().__init__(output)
        self.journey = journey
        self.producer_hash = sha(__file__)
        self.support = {"data_preservation.py": sha(Path(__file__).with_name("data_preservation.py"))}
        self.fixtures = []
        self.holders = []
        self.save("case-contract.json", {"journey": journey, "producer": JOURNEYS[journey]["producer"],
                  "outcome": JOURNEYS[journey]["outcome"], "literal_case_ids": list(JOURNEYS[journey]["cases"]),
                  "product_hashes": self.sources, "producer_sha256": self.producer_hash,
                  "support_producer_hashes": self.support, "contract_frozen_before_any_product_invocation": True})

    def add(self, identifier, expected, observed, passed, evidence):
        self.cases.append({"id": "recovery." + self.journey + "." + identifier, "verdict": "PASS" if passed else "FAIL",
                           "expected": expected, "observed": observed, "evidence": evidence})
        print(self.cases[-1]["verdict"] + " " + self.cases[-1]["id"], flush=True)

    def activate(self, fixture):
        self.env["PYTHONPATH"] = str(fixture["toolkit"])
        self.env["KNOWLEDGEOS_STATE_DIR"] = str(fixture["scope"] / "gate-state")
        self.env["KNOWLEDGEOS_VAULT"] = str(fixture["vault"])

    def cli(self, label, fixture, arguments, fault=False):
        self.activate(fixture)
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", *arguments]
        if fault:
            code = "import resource,runpy,signal,sys; signal.signal(signal.SIGXFSZ,signal.SIG_IGN); resource.setrlimit(resource.RLIMIT_FSIZE,(1,1)); sys.argv=['knowledgeos',*sys.argv[1:]]; runpy.run_module('knowledgeos',run_name='__main__')"
            command = [sys.executable, "-B", "-P", "-c", code, *arguments]
        record, stdout, stderr = self.command(label, command, fixture["scope"], fixture["vault"], timeout=160)
        record["import_path"] = self.env["PYTHONPATH"]
        record["os_fault"] = "RLIMIT_FSIZE=1 byte; SIGXFSZ ignored so kernel EFBIG is observable" if fault else None
        self.save(label + ".command.json", record)
        return record, stdout, stderr

    def rebuild(self, label, fixture, fault=False):
        self.activate(fixture)
        script = fixture["toolkit"] / "scripts/rebuild_index.py"
        command = [sys.executable, "-B", "-P", str(script), "--vault", str(fixture["vault"])]
        if fault:
            code = "import resource,runpy,signal,sys; signal.signal(signal.SIGXFSZ,signal.SIG_IGN); resource.setrlimit(resource.RLIMIT_FSIZE,(1,1)); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
            command = [sys.executable, "-B", "-P", "-c", code, str(script), "--vault", str(fixture["vault"])]
        record, stdout, stderr = self.command(label, command, fixture["scope"], fixture["vault"], timeout=70)
        record.update(import_path=self.env["PYTHONPATH"], os_fault="RLIMIT_FSIZE=1; actual kernel EFBIG" if fault else None)
        self.save(label + ".command.json", record)
        return record, stdout, stderr

    def rpc(self, label, fixture, calls):
        self.activate(fixture)
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05",
                     "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-recovery", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        requests += [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
                     for i, (name, arguments) in enumerate(calls, 2)]
        self.save(label + ".requests.json", requests)
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", str(fixture["vault"]), "--framing", "ndjson"]
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=fixture["scope"], env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8")
        tracked = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(tracked)
        error, interrupted = None, None
        try:
            stdout, stderr = process.communicate("".join(json.dumps(row) + "\n" for row in requests), timeout=180)
        except BaseException as caught:
            process.kill()
            stdout, stderr = process.communicate()
            error = str(caught)
            interrupted = caught if not isinstance(caught, subprocess.TimeoutExpired) else None
        finally:
            tracked.update(stopped=process.poll() is not None, exit_code=process.returncode)
        (self.directory / (label + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (self.directory / (label + ".stderr.txt")).write_text(stderr, encoding="utf-8")
        record = {"command": command, "cwd": str(fixture["scope"]), "shell": False, "vault": str(fixture["vault"]),
                  "state_dir": self.env["KNOWLEDGEOS_STATE_DIR"], "import_path": self.env["PYTHONPATH"], "pid": process.pid,
                  "seconds": time.monotonic() - started, "exit_code": process.returncode, "stopped": tracked["stopped"], "error": error}
        self.save(label + ".command.json", record)
        if interrupted:
            raise interrupted
        if error or process.returncode:
            raise RuntimeError(error or "Recovery MCP exited " + str(process.returncode))
        responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        by_id = {row.get("id"): row for row in responses}
        if len(responses) != len(calls) + 1 or set(by_id) != set(range(1, len(calls) + 2)) or by_id[1].get("result", {}).get("serverInfo", {}).get("name") != "knowledgeos-memory":
            raise ValueError("Unexpected public MCP response inventory or server identity")
        results = []
        for i in range(2, len(calls) + 2):
            result = by_id[i]["result"]
            content = result.get("content")
            if not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "text" or not isinstance(result.get("isError"), bool):
                raise ValueError("Unexpected MCP content or protocol-error shape")
            payload = json.loads(content[0]["text"])
            if not isinstance(payload, dict):
                raise ValueError("Public MCP tool payload must be an object")
            results.append({"is_error": result["isError"], "payload": payload})
        self.save(label + ".results.json", results)
        return results

    def prepare(self, label):
        scope = self.directory / "fixtures" / label
        toolkit, vault = scope / "toolkit", scope / "vault"
        toolkit.mkdir(parents=True)
        for source in self.inputs:
            destination = toolkit / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        fixture = {"label": label, "scope": scope, "toolkit": toolkit, "vault": vault}
        self.fixtures.append(fixture)
        self.save(label + ".toolkit-before.json", inventory(toolkit))
        record, stdout, _ = self.cli(label + "-init", fixture, ["init", str(vault), "--name", "Synthetic Recovery RQ731", "--non-interactive"])
        initialized = json.loads(stdout) if record["exit_code"] == 0 else {}
        post = initialized.get("post_init", {})
        ready = record["exit_code"] == 0 and record["error"] is None and set(post) >= {"rebuild", "validate"} and all(row.get("ok") is True for row in post.values())
        if not ready:
            raise RuntimeError("Recovery fixture initialization failed; inspect retained command before treating sandbox failure as product behavior")
        (vault / "Concepts/Recovery.md").write_bytes(note("rq731 recovery", ORIGINAL_QUOTE, "rq731-recovery"))
        (vault / "Concepts/Removed.md").write_bytes(note("rq731 removed", "rq731 note later removed by its synthetic editor.", "rq731-removed"))
        record, _, _ = self.rebuild(label + "-bootstrap", fixture)
        doctor, out, err = self.cli(label + "-doctor", fixture, ["doctor", "--vault", str(vault)])
        fixture["ready"] = record["exit_code"] == 0 and record["error"] is None and doctor["exit_code"] == 0 and doctor["error"] is None
        fixture["initialization"] = {"initialized": initialized, "rebuild_exit": record["exit_code"], "doctor_exit": doctor["exit_code"], "doctor_stdout": out, "doctor_stderr": err}
        if not fixture["ready"]:
            raise RuntimeError("Fresh recovery fixture failed rebuild or doctor")
        fixture["toolkit_before"] = inventory(toolkit)
        return fixture

    def snapshot(self, fixture, label):
        state = scope_inventory(fixture["scope"])
        self.save(label + ".inventory.json", state)
        return state

    def preservation(self, fixture, before, label):
        after = self.snapshot(fixture, label)
        protected = {p: row for p, row in before.items() if p.startswith("toolkit/") or
                     p.startswith("vault/") and not p.startswith("vault/.knowledgeos/") and not p.startswith("vault/knowledge_index.db") and
                     not p.startswith("vault/People/Self-Proposals/")}
        changed = sorted(p for p, row in protected.items() if after.get(p) != row)
        notes = {p: row for p, row in before.items() if p.startswith("vault/") and p.endswith(".md") and not p.startswith("vault/People/Self-Proposals/")}
        new_notes = sorted(p for p in after if p.startswith("vault/") and p.endswith(".md") and p not in notes and not p.startswith("vault/People/Self-Proposals/"))
        return {"complete_copied_toolkit_unchanged": inventory(fixture["toolkit"]) == fixture["toolkit_before"],
                "source_and_unrelated_files_unchanged": not changed and not new_notes, "changed_protected_entries": changed,
                "unexpected_new_notes": new_notes, "self_sha256": sha(fixture["vault"] / "People/Self.md")}

    def hold(self, label, fixture, kind):
        self.activate(fixture)
        command = [sys.executable, "-B", "-P", "-c", HOLDER_CODE, str(fixture["vault"]), kind]
        output = open(self.directory / (label + ".stdout.txt"), "w", encoding="utf-8")
        errors = open(self.directory / (label + ".stderr.txt"), "w", encoding="utf-8")
        process = subprocess.Popen(command, cwd=fixture["scope"], env=self.env, stdin=subprocess.PIPE, stdout=output, stderr=errors, text=True, encoding="utf-8")
        tracked = {"pid": process.pid, "role": label, "stopped": False, "helper": True}
        self.processes.append(tracked)
        record = {"command": command, "cwd": str(fixture["scope"]), "shell": False, "vault": str(fixture["vault"]),
                  "state_dir": self.env["KNOWLEDGEOS_STATE_DIR"], "import_path": self.env["PYTHONPATH"], "pid": process.pid,
                  "role": "actual held " + kind + " lock", "stopped": False}
        holder = {"process": process, "tracked": tracked, "record": record, "label": label, "output": output, "errors": errors}
        self.holders.append(holder)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            lines = (self.directory / (label + ".stdout.txt")).read_text(encoding="utf-8").splitlines()
            if lines:
                ready = json.loads(lines[0])
                if ready.get("ready") is True and ready.get("pid") == process.pid and ready.get("kind") == kind and process.poll() is None:
                    holder["ready"] = ready
                    record["ready_observation"] = ready
                    self.save(label + ".command.json", record)
                    return holder
            if process.poll() is not None:
                break
            time.sleep(0.025)
        self.stop_holder(holder)
        raise RuntimeError("Real holder failed readiness; inspect " + label)

    def stop_holder(self, holder, kill=False):
        process = holder["process"]
        if process.poll() is None:
            if kill:
                process.kill()
            try:
                process.communicate("", timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                holder["record"]["forced_after_timeout"] = True
        holder["output"].close()
        holder["errors"].close()
        holder["tracked"].update(stopped=process.poll() is not None, exit_code=process.returncode)
        holder["record"].update(stopped=process.poll() is not None, exit_code=process.returncode, terminated_exact_owned_child=kill,
                                 ready_was_observed=bool(holder.get("ready")))
        self.save(holder["label"] + ".command.json", holder["record"])

    def paths_for(self, fixture, kind):
        if kind in ("index", "sessions"):
            return fixture["vault"] / ".knowledgeos" / ("index-rebuild.lock" if kind == "index" else "sessions.lock")
        locks = sorted((fixture["scope"] / "gate-state/vaults").glob("*/self-gate.lock.guard"))
        if not locks:
            label = fixture["label"] + "-gate-readiness"
            result = self.rpc(label, fixture, [("memory_propose_self_update", {"summary": "Synthetic gate readiness RQ731",
                         "section": "heuristics", "proposed_markdown": "- Synthetic fixture gate readiness only.", "mode": "append"})])[0]
            if not public_success(result, "gate"):
                raise RuntimeError("Public synthetic proposal failed gate readiness")
            locks = sorted((fixture["scope"] / "gate-state/vaults").glob("*/self-gate.lock.guard"))
        if len(locks) != 1:
            raise RuntimeError("Synthetic gate has no unique retained guard")
        return locks[0].with_name("self-gate.lock")

    def action(self, label, fixture, kind, fault=False):
        if kind == "index":
            record, stdout, stderr = self.rebuild(label, fixture, fault=fault)
            return {"success": record["exit_code"] == 0 and record["error"] is None, "exit_code": record["exit_code"], "stdout": stdout, "stderr": stderr, "command": record}
        name = "memory_propose_self_update" if kind == "gate" else "memory_session_start"
        arguments = {"summary": "Synthetic recovery check", "section": "heuristics", "proposed_markdown": "- Synthetic rq731 proposal; no personal claim.", "mode": "append"} if kind == "gate" else {
            "task_hint": QUERY, "session_id": "rq731-ownership-session"}
        if fault:
            record, stdout, stderr = self.cli(label, fixture, ["memory", name, "--vault", str(fixture["vault"]), "--args", json.dumps(arguments)], fault=True)
            try:
                payload = json.loads(stdout)
            except ValueError:
                payload = {}
            return {"success": record["exit_code"] == 0 and "error" not in payload, "payload": payload, "command": record, "stdout": stdout, "stderr": stderr}
        result = self.rpc(label, fixture, [(name, arguments)])[0]
        success = public_success(result, kind)
        if success and kind == "gate":
            relative = result["payload"]["proposal_path"]
            candidate = fixture["vault"] / relative
            success = candidate.is_file() and candidate.resolve().is_relative_to(fixture["vault"].resolve()) and not candidate.is_symlink() and candidate.stat().st_nlink == 1
        return {"success": success, "result": result}

    def evidence(self, *labels):
        return [p.name for label in labels for p in sorted(self.directory.glob(label + ".*")) if p.is_file()]

    def index_case(self, identifier, fixture=None):
        fixture = fixture or self.prepare(identifier)
        vault = fixture["vault"]
        database = vault / "knowledge_index.db"
        holder = None
        obstruction = None
        retained = None
        if identifier == "missing_index":
            retained = database.with_name(database.name + ".removed-by-fixture")
            database.replace(retained)
        elif identifier == "corrupt_index":
            retained = database.with_name(database.name + ".before-corruption")
            database.replace(retained)
            database.write_bytes(b"NOT A SQLITE DATABASE RQ731\x00\xff\n")
        elif identifier in ("busy_sqlite", "busy_rebuild"):
            holder = self.hold(identifier + "-holder", fixture, "sqlite" if identifier == "busy_sqlite" else "index")
        elif identifier == "blocked_rebuild":
            obstruction = vault / ".knowledgeos/index-rebuild.lock"
            obstruction.mkdir()
            (obstruction / "unrelated-owner.bin").write_bytes(OBSTRUCTION)
        elif identifier == "blocked_manifest":
            obstruction = vault / ".knowledgeos/index-manifest.json"
            obstruction.replace(obstruction.with_name(obstruction.name + ".before-obstruction"))
            obstruction.mkdir()
            (obstruction / "unrelated-owner.bin").write_bytes(OBSTRUCTION)
        (vault / "Concepts/Recovery.md").write_bytes(note("rq731 recovery", CURRENT_QUOTE, "rq731-recovery"))
        (vault / "Concepts/Removed.md").replace(vault / ".knowledgeos/removed-note-by-fixture.bin")
        (vault / "Concepts/Fresh.md").write_bytes(note("rq731 fresh", FRESH_QUOTE, "rq731-fresh"))
        before = self.snapshot(fixture, identifier + "-before")
        database_identity = (database.stat().st_dev, database.stat().st_ino) if database.is_file() else None
        frozen = identifier not in ("missing_index", "corrupt_index")
        try:
            result = self.rpc(identifier + "-during", fixture, [("memory_search", {"query": QUERY, "limit": 20})])[0]
            observed = search_observation(result, frozen=frozen, require_fresh=not frozen)
            observed["source_preservation_during"] = self.preservation(fixture, before, identifier + "-during-after")
            observed["holder_alive_during"] = holder["process"].poll() is None if holder else None
            observed["live_database_not_replaced"] = (database.stat().st_dev, database.stat().st_ino) == database_identity if identifier == "busy_sqlite" else None
            observed["obstruction_preserved"] = (obstruction / "unrelated-owner.bin").read_bytes() == OBSTRUCTION if obstruction else None
            if identifier == "corrupt_index":
                observed["corrupt_bytes_retained"] = any(p.read_bytes() == b"NOT A SQLITE DATABASE RQ731\x00\xff\n" for p in vault.glob("knowledge_index.db.corrupt-*") if p.is_file())
            if retained:
                observed["fixture_retained_database_unchanged"] = sha(retained) == before["vault/" + retained.name]["sha256"]
        finally:
            if holder:
                self.stop_holder(holder)
        if obstruction:
            obstruction.replace(obstruction.with_name(obstruction.name + ".released-by-fixture"))
        retry = self.rpc(identifier + "-retry", fixture, [("memory_search", {"query": QUERY, "limit": 20})])[0]
        observed["retry"] = search_observation(retry, frozen=False, require_fresh=True)
        observed["source_preservation_after_retry"] = self.preservation(fixture, before, identifier + "-retry-after")
        preserved = all(observed[key]["source_and_unrelated_files_unchanged"] and observed[key]["complete_copied_toolkit_unchanged"] for key in ("source_preservation_during", "source_preservation_after_retry"))
        passed = observed["valid"] and observed["retry"]["valid"] and preserved
        if holder:
            passed = passed and observed["holder_alive_during"] and holder["tracked"]["stopped"]
        for key in ("live_database_not_replaced", "obstruction_preserved", "corrupt_bytes_retained", "fixture_retained_database_unchanged"):
            if observed.get(key) is not None:
                passed = passed and observed[key]
        self.add(identifier, "Missing/corrupt cache recovers; unavailable refresh discloses incomplete current-file quotes; all source and unrelated ownership survive; releasing the exact obstruction permits autonomous retry",
                 observed, passed, self.evidence(identifier + "-before", identifier + "-during", identifier + "-during-after", identifier + "-retry", identifier + "-retry-after", identifier + "-holder"))

    def lock_case(self, fixture, kind, scenario):
        identifier = kind + "_" + scenario
        path = self.paths_for(fixture, kind)
        guard = path.with_name(path.name + ".guard")
        holder = None
        observed = {}
        before = self.snapshot(fixture, identifier + "-before")
        try:
            if scenario in ("live_old_owner", "dead_owner", "replacement_marker"):
                holder = self.hold(identifier + "-holder", fixture, kind)
                token = path.read_bytes()
                observed["actual_owner"] = holder["ready"]
                if scenario == "live_old_owner":
                    threshold = holder["ready"]["stale_threshold_seconds"]
                    age = max(2000.0, (threshold or 0) + 100)
                    stamp = time.time() - age
                    os.utime(path, (stamp, stamp))
                    observed["marker_age_seconds"] = time.time() - path.stat().st_mtime
                    observed["production_timeout_and_threshold_unchanged"] = True
                    during = self.action(identifier + "-contender", fixture, kind)
                    observed.update(contender=during, live_owner_alive=holder["process"].poll() is None,
                                    owned_marker_unchanged=path.read_bytes() == token)
                    passed = refused(during) and observed["live_owner_alive"] and observed["owned_marker_unchanged"] and observed["marker_age_seconds"] > (threshold or 0)
                    self.stop_holder(holder)
                    retry = self.action(identifier + "-retry", fixture, kind)
                    observed["retry"] = retry
                    passed = passed and retry["success"] and not path.exists()
                elif scenario == "dead_owner":
                    self.stop_holder(holder, kill=True)
                    observed["dead_owner_marker_retained_before_retry"] = path.read_bytes() == token
                    started = time.monotonic()
                    retry = self.action(identifier + "-retry", fixture, kind)
                    observed.update(retry=retry, recovery_seconds=time.monotonic() - started)
                    passed = observed["dead_owner_marker_retained_before_retry"] and retry["success"] and not path.exists() and observed["recovery_seconds"] < 20
                else:
                    retained = path.with_name(path.name + ".original-token-retained")
                    path.replace(retained)
                    path.write_bytes(REPLACEMENT)
                    self.stop_holder(holder)
                    observed.update(replacement_marker_preserved=path.read_bytes() == REPLACEMENT,
                                    original_marker_retained=retained.read_bytes() == token)
                    passed = observed["replacement_marker_preserved"] and observed["original_marker_retained"]
                    path.replace(path.with_name(path.name + ".replacement-retained"))
                    retry = self.action(identifier + "-retry", fixture, kind)
                    observed["retry"] = retry
                    passed = passed and retry["success"] and not path.exists()
            else:
                target = path if scenario == "blocked_marker" else guard
                retained = target.with_name(target.name + ".before-fixture-obstruction")
                if target.exists():
                    target.replace(retained)
                target.mkdir()
                (target / "unrelated-owner.bin").write_bytes(OBSTRUCTION)
                during = self.action(identifier + "-contender", fixture, kind)
                observed.update(contender=during, unrelated_ownership_preserved=(target / "unrelated-owner.bin").read_bytes() == OBSTRUCTION)
                passed = refused(during) and observed["unrelated_ownership_preserved"]
                target.replace(target.with_name(target.name + ".obstruction-retained"))
                if retained.exists():
                    retained.replace(target)
                retry = self.action(identifier + "-retry", fixture, kind)
                observed["retry"] = retry
                passed = passed and retry["success"] and not path.exists()
        finally:
            if holder and holder["process"].poll() is None:
                self.stop_holder(holder)
        observed["source_preservation"] = self.preservation(fixture, before, identifier + "-after")
        passed = passed and observed["source_preservation"]["source_and_unrelated_files_unchanged"] and observed["source_preservation"]["complete_copied_toolkit_unchanged"]
        self.add(identifier, "Production lock timeout does not steal a live old owner; exact dead owner recovers; old owner does not remove a replacement; native failed creation preserves unrelated ownership and later retry succeeds",
                 observed, passed, self.evidence(identifier + "-before", identifier + "-after", identifier + "-holder", identifier + "-contender", identifier + "-retry"))

    def write_fault(self, kind):
        identifier = kind + "_partial_marker_write"
        if os.name != "posix":
            self.cases.append({"id": "recovery.write-faults." + identifier, "verdict": "NOT CHECKED", "expected": "Actual kernel EFBIG during marker publication, no orphan token, safe retry", "observed": {"reason": "Requires native POSIX RLIMIT_FSIZE"}, "evidence": ["case-contract.json"]})
            return
        fixture = self.prepare(identifier)
        path = self.paths_for(fixture, kind)
        before = self.snapshot(fixture, identifier + "-before")
        failure = self.action(identifier + "-fault", fixture, kind, fault=True)
        observed = {"failure": failure, "partial_marker_absent_after_failure": not path.exists()}
        retry = self.action(identifier + "-retry", fixture, kind)
        observed["retry"] = retry
        observed["source_preservation"] = self.preservation(fixture, before, identifier + "-after")
        diagnostic = json.dumps(failure).lower()
        passed = not failure["success"] and ("file too large" in diagnostic or "efbig" in diagnostic) and observed["partial_marker_absent_after_failure"] and retry["success"] and not path.exists()
        passed = passed and observed["source_preservation"]["source_and_unrelated_files_unchanged"] and observed["source_preservation"]["complete_copied_toolkit_unchanged"]
        self.add(identifier, "Native RLIMIT_FSIZE causes actual EFBIG during owner token write; the attempt removes only its partial token; source survives and unchanged public retry succeeds",
                 observed, passed, self.evidence(identifier + "-before", identifier + "-fault", identifier + "-retry", identifier + "-after"))

    def finish(self, error=None):
        for holder in self.holders:
            if not holder["tracked"]["stopped"]:
                self.stop_holder(holder)
        after = self.sentinels()
        current = {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files()}
        support = {name: sha(Path(__file__).with_name(name)) for name in self.support}
        stable = current == self.sources and sha(__file__) == self.producer_hash and support == self.support
        stopped = bool(self.processes) and all(row["stopped"] and isinstance(row.get("exit_code"), int) for row in self.processes)
        expected = ["recovery." + self.journey + "." + name for name in JOURNEYS[self.journey]["cases"]]
        complete = [case["id"] for case in self.cases] == expected
        fixture_rows = []
        for fixture in self.fixtures:
            toolkit_after = inventory(fixture["toolkit"])
            self.save(fixture["label"] + ".toolkit-after.json", toolkit_after)
            fixture_rows.append({"label": fixture["label"], "scope": str(fixture["scope"]), "vault": str(fixture["vault"]),
                                 "toolkit": str(fixture["toolkit"]), "initialization": fixture["initialization"],
                                 "complete_toolkit_matches_current_source": {p: row.get("sha256") for p, row in toolkit_after.items() if row["kind"] == "file"} == self.sources})
        passed = error is None and stable and stopped and self.before == after and complete and all(row["verdict"] == "PASS" for row in self.cases) and all(row["complete_toolkit_matches_current_source"] for row in fixture_rows)
        report = {"producer": JOURNEYS[self.journey]["producer"], "producer_sha256": self.producer_hash,
                  "support_producer_hashes": self.support, "source_root": str(ROOT), "revision": getattr(self, "revision", None),
                  "platform": platform.platform(), "os_name": os.name, "python": sys.version, "journey": self.journey,
                  "scope": "source CLI/MCP with complete copied toolkit, synthetic identities and native OS locks/faults; no host or owner approval",
                  "verdict": "PASS" if passed else "FAIL", "ideal_system_verdict": "NOT CHECKED", "fixed_outcome_candidate": JOURNEYS[self.journey]["outcome"],
                  "acceptance_credit_awarded": False, "product_hashes": self.sources, "product_hashes_after": current,
                  "support_producer_hashes_after": support, "product_and_producer_unchanged": stable,
                  "case_inventory_complete": complete, "cases": self.cases, "processes": self.processes,
                  "all_started_processes_stopped": stopped, "fixtures": fixture_rows,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after,
                                "limitation": "Selected real-vault sentinels only, not an exhaustive filesystem audit"},
                  "limitations": ["No installed artifact, real host, independent owner approval or privacy claim", "Lock markers were aged in synthetic fixtures; production timeout and threshold constants were not changed",
                                  "Native partial-write faults require the separate write-faults journey on POSIX", "No filesystem cleanup or collection is authorized"],
                  "error": str(error) if error else None}
        if error:
            self.save("execution-error.json", {"error": str(error), "type": type(error).__name__})
        report["evidence_files"] = {p.name: sha(p) for p in sorted(self.directory.iterdir()) if p.is_file() and p.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"], "passed": sum(row["verdict"] == "PASS" for row in self.cases), "total": len(expected)}), flush=True)
        return 0 if passed else 1

    def run(self):
        error = None
        try:
            _, output, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            self.revision = output.strip()
            if self.journey == "index":
                for identifier in INDEX_CASES:
                    self.index_case(identifier)
            elif self.journey == "locks":
                for kind in LOCK_KINDS:
                    fixture = self.prepare("ownership-" + kind)
                    for scenario in LOCK_SCENARIOS:
                        self.lock_case(fixture, kind, scenario)
            else:
                for kind in LOCK_KINDS:
                    self.write_fault(kind)
        except BaseException as caught:
            error = caught
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journey", choices=JOURNEYS, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError("Recovery proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return RecoveryRun(args.output, args.journey).run()


if __name__ == "__main__":
    raise SystemExit(main())
