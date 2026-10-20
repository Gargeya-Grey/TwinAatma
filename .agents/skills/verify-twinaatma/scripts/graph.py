"""Observe literal note relationships through public source CLI and MCP processes."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import signal
import subprocess
import sys
import threading
import time

from data_preservation import ROOT, inventory, sha, source_files
from identity import IdentityRun

PRODUCER = "verify-twinaatma.graph/v1"
OUTCOME = "MEMORY.correct_links"
CASES = {
    "markdown_local": ("Projects/A/LocalSource.md", ["Projects/A/Target.md"], 1),
    "markdown_parent": ("Projects/A/Sub/ParentSource.md", ["Projects/A/ParentTarget.md"], 1),
    "markdown_root": ("Projects/A/RootSource.md", ["Target.md"], 1),
    "wikilink_path": ("Projects/A/ExplicitSource.md", ["Projects/B/ExplicitTarget.md"], 1),
    "wikilink_alias_anchor": ("Projects/A/AliasSource.md", ["Projects/B/AnchorTarget.md"], 1),
    "markdown_encoded_anchor": ("Projects/A/EncodedSource.md", ["Concepts/Space Name.md"], 1),
    "unique_basename": ("Projects/A/UniqueSource.md", ["Concepts/UniqueDestination.md"], 1),
    "ambiguous_basename": ("Projects/A/AmbiguousSource.md", [], 1),
    "missing_target": ("Projects/A/MissingSource.md", [], 1),
    "fenced_examples": ("Projects/A/FencedSource.md", ["Concepts/ActualExampleTarget.md"], 1),
    "incoming_links": ("Concepts/IncomingTarget.md", ["Projects/A/IncomingSource.md"], 1),
    "two_hop": ("Concepts/ChainSeed.md", ["Concepts/ChainLeaf.md", "Concepts/ChainMiddle.md"], 2),
}
CASE_IDS = ("fixture_init", *CASES, "source_edit_refresh", "target_move_refresh", "source_preserved")
AMBIGUITY = {"source": "Projects/A/AmbiguousSource.md", "target": "Twin",
             "candidates": ["Concepts/Twin.md", "Projects/B/Twin.md"]}
BODIES = {
    "Target.md": "# Root collision target\n",
    "Projects/A/Target.md": "# Local collision target\n",
    "Projects/A/LocalSource.md": "# Local source\n[Local](Target.md)\n",
    "Projects/A/ParentTarget.md": "# Parent target\n",
    "Projects/A/Sub/ParentSource.md": "# Parent source\n[Parent](../ParentTarget.md)\n",
    "Projects/A/RootSource.md": "# Root source\n[Root](/Target.md)\n",
    "Projects/B/ExplicitTarget.md": "# Explicit target\n",
    "Projects/A/ExplicitSource.md": "# Explicit source\n[[Projects/B/ExplicitTarget]]\n",
    "Projects/B/AnchorTarget.md": "# Anchor target\n## Section\n",
    "Projects/A/AliasSource.md": "# Alias source\n[[Projects/B/AnchorTarget#Section|Friendly label]]\n",
    "Concepts/Space Name.md": "# Encoded target\n## Section\n",
    "Projects/A/EncodedSource.md": "# Encoded source\n[Encoded](../../Concepts/Space%20Name.md#Section)\n",
    "Concepts/UniqueDestination.md": "# Unique target\n",
    "Projects/A/UniqueSource.md": "# Unique source\n[[UniqueDestination]]\n",
    "Concepts/Twin.md": "# First Twin\n",
    "Projects/B/Twin.md": "# Second Twin\n",
    "Projects/A/AmbiguousSource.md": "# Ambiguous source\n[[Twin]]\n",
    "Projects/A/MissingSource.md": "# Missing source\n[Missing](AbsentDestination.md)\n[[UnknownGhost]]\n",
    "Concepts/ActualExampleTarget.md": "# Actual example target\n",
    "Concepts/FencedFake.md": "# Fenced fake target\n",
    "Projects/A/FencedSource.md": "# Fenced source\n[[Concepts/ActualExampleTarget]]\n```markdown\n[Not a relation](../../Target.md)\n```\n~~~text\n[[Concepts/FencedFake]]\n~~~\n",
    "Concepts/IncomingTarget.md": "# Incoming target\n",
    "Projects/A/IncomingSource.md": "# Incoming source\n[[Concepts/IncomingTarget]]\n",
    "Concepts/ChainSeed.md": "# Chain seed\n[[Concepts/ChainMiddle]]\n",
    "Concepts/ChainMiddle.md": "# Chain middle\n[[Concepts/ChainLeaf]]\n",
    "Concepts/ChainLeaf.md": "# Chain leaf\n",
    "Concepts/EditSeed.md": "# Edit seed\n[[Concepts/EditOld]]\n",
    "Concepts/EditOld.md": "# Old edit target\n",
    "Concepts/EditNew.md": "# New edit target\n",
    "Concepts/MoveSeed.md": "# Move seed\n[[Concepts/MoveTarget]]\n",
    "Concepts/MoveTarget.md": "# Move target\n",
}
EDITED_BODY = "# Edit seed\n[[Concepts/EditNew]]\n"
MOVED_BODY = "# Move seed\n[[Concepts/Archive/RenamedTarget]]\n"
TRACE_SOURCE = '''import atexit, json, os, subprocess
from pathlib import Path
_graph_children = []
_graph_popen = subprocess.Popen
class GraphObservedPopen(_graph_popen):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        argv = args[0] if args else kwargs.get("args", [])
        _graph_children.append((self, [str(value) for value in argv] if isinstance(argv, (list, tuple)) else [str(argv)]))
subprocess.Popen = GraphObservedPopen
def _graph_shutdown():
    rows = []
    for child, argv in _graph_children:
        forced = child.poll() is None
        if forced:
            child.kill()
        child.wait()
        rows.append({"pid": child.pid, "argv": argv, "stopped": child.poll() is not None,
                     "exit_code": child.returncode, "cleanup_required": forced})
    target = Path(os.environ["TWIN_GRAPH_TRACE_DIR"]) / (str(os.getpid()) + ".json")
    target.write_text(json.dumps({"pid": os.getpid(), "parent_pid": os.getppid(), "children": rows}), encoding="utf-8")
atexit.register(_graph_shutdown)
'''


def note(relative, body):
    title = Path(relative).stem
    return ("---\ntype: concept\ntitle: " + title + "\ndescription: Frozen synthetic graph evidence\nstatus: active\n"
            "schema: knowledgeos-v0.3\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [synthetic]\n---\n" + body).encode("utf-8")


def has_ambiguity(payload):
    """Require an explicit ambiguous diagnostic and both literal candidate paths."""
    if not isinstance(payload, dict):
        return False
    pending = [("", payload)]
    while pending:
        key, value = pending.pop()
        if isinstance(value, dict):
            kind = str(value.get("issue", value.get("kind", value.get("type", key)))).lower()
            source = value.get("source", value.get("path", value.get("source_path", payload.get("seed"))))
            candidates = value.get("candidates")
            if ("ambigu" in kind and source == AMBIGUITY["source"] and value.get("target") == AMBIGUITY["target"]
                    and isinstance(candidates, list) and all(isinstance(item, str) for item in candidates)
                    and sorted(candidates) == AMBIGUITY["candidates"]):
                return True
            pending.extend(value.items())
        elif isinstance(value, list):
            pending.extend((key, item) for item in value)
    return False


def related_observation(result, source, expected, hops=1, ambiguity=False):
    payload = result.get("payload") if isinstance(result, dict) else None
    rows = payload.get("related") if isinstance(payload, dict) else None
    paths = [row["path"] for row in rows] if isinstance(rows, list) and all(isinstance(row, dict) and isinstance(row.get("path"), str) for row in rows) else None
    exact = (isinstance(result, dict) and result.get("is_error") is False and isinstance(payload, dict)
             and payload.get("seed") == source and type(payload.get("hops")) is int and payload["hops"] == hops
             and paths is not None and sorted(paths) == expected
             and len(set(paths or [])) == len(paths or []))
    disclosed = has_ambiguity(payload) if ambiguity else None
    return {"source": source, "expected_paths": expected, "actual_paths": paths, "hops": hops,
            "exact_neighbors": exact, "ambiguity_disclosed": disclosed, "public_result": result,
            "valid": exact and (disclosed if ambiguity else True)}


class GraphRun(IdentityRun):
    def __init__(self, output):
        super().__init__(output, "unknown")
        self.producer_hash = sha(__file__)
        self.support = {name: sha(Path(__file__).with_name(name)) for name in ("data_preservation.py", "identity.py")}
        self.trace_directory = self.directory / "child-traces"
        self.trace_directory.mkdir()
        self.tracer = self.directory / "tracer/sitecustomize.py"
        self.tracer.parent.mkdir()
        self.tracer.write_text(TRACE_SOURCE, encoding="utf-8")
        self.trace_hash = sha(self.tracer)
        self.fixture_state = None
        self.mutations = []
        self.save("frozen-expectations.json", {"producer": PRODUCER, "outcome": OUTCOME,
                  "expected_case_ids": ["memory.graph." + value for value in CASE_IDS],
                  "relationships": CASES, "ambiguity": AMBIGUITY, "note_bodies": BODIES,
                  "editor_changes": {"Concepts/EditSeed.md": EDITED_BODY, "Concepts/MoveSeed.md": MOVED_BODY,
                                     "rename": ["Concepts/MoveTarget.md", "Concepts/Archive/RenamedTarget.md"]}})

    def activate(self, fixture):
        super().activate(fixture)
        self.env["PYTHONPATH"] = str(self.tracer.parent) + os.pathsep + self.env["PYTHONPATH"]
        self.env["TWIN_GRAPH_TRACE_DIR"] = str(self.trace_directory)

    def add_case(self, name, expected, observed, passed, evidence):
        self.cases.append({"id": "memory.graph." + name, "verdict": "PASS" if passed else "FAIL",
                           "expected": expected, "observed": observed, "evidence": evidence})
        print(self.cases[-1]["verdict"] + " " + self.cases[-1]["id"], flush=True)

    def prepare_graph(self):
        fixture = self.prepare("cold")
        self.fixture_state = fixture
        self.add_case("fixture_init", "Name-only public CLI initialization, complete post-init checks and doctor succeed",
                      fixture["initialization"], fixture["ready"], ["cold-init.command.json", "cold-init.stdout.txt", "cold-doctor.command.json", "cold-doctor.stdout.txt"])
        for relative, body in BODIES.items():
            path = fixture["vault"] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(note(relative, body))
        (fixture["vault"] / "Concepts/Archive").mkdir()
        self.scope_before = inventory(fixture["scope"])
        self.save("graph.before.json", self.scope_before)
        return fixture

    def rpc_events(self, fixture, events, label="graph"):
        self.activate(fixture)
        command = [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", str(fixture["vault"]), "--framing", "ndjson"]
        env = dict(self.env, KNOWLEDGEOS_VAULT=str(fixture["vault"]))
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=fixture["scope"], env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        tracked = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(tracked)
        received, lines, errors = queue.Queue(), [], []
        def read_output():
            for line in process.stdout:
                lines.append(line)
                received.put(line)
            received.put(None)
        def read_errors():
            errors.extend(process.stderr.readlines())
        readers = [threading.Thread(target=read_output, daemon=True), threading.Thread(target=read_errors, daemon=True)]
        for thread in readers:
            thread.start()
        requests, results, error = [], [], None
        def exchange(message, response=True):
            requests.append(message)
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
            if not response:
                return None
            raw = received.get(timeout=90)
            if raw is None:
                raise RuntimeError("MCP closed before its expected response")
            answer = json.loads(raw)
            if answer.get("jsonrpc") != "2.0" or answer.get("id") != message["id"] or "error" in answer:
                raise ValueError("MCP response does not match its request")
            return answer["result"]
        try:
            initialized = exchange({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-twinaatma-graph", "version": "1"}}})
            if initialized.get("serverInfo", {}).get("name") != "knowledgeos-memory":
                raise ValueError("Wrong MCP server identity")
            exchange({"jsonrpc": "2.0", "method": "notifications/initialized"}, response=False)
            for number, event in enumerate(events, 2):
                if event.get("editor_action"):
                    self.edit(fixture, event["editor_action"])
                result = exchange({"jsonrpc": "2.0", "id": number, "method": "tools/call", "params": {
                    "name": "memory_related", "arguments": {"path_or_id": event["source"], "hops": event.get("hops", 1), "limit": 30}}})
                content = result.get("content")
                if not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "text" or not isinstance(result.get("isError"), bool):
                    raise ValueError("Malformed public MCP tool result")
                payload = json.loads(content[0]["text"])
                if not isinstance(payload, dict):
                    raise ValueError("MCP graph payload must be an object")
                results.append({"payload": payload, "is_error": result["isError"]})
            process.stdin.close()
            process.wait(timeout=30)
        except BaseException as caught:
            error = caught
            if process.poll() is None:
                process.kill()
            process.wait(timeout=30)
        finally:
            for thread in readers:
                thread.join(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
            tracked.update(stopped=process.poll() is not None, exit_code=process.returncode)
            (self.directory / (label + ".stdout.txt")).write_text("".join(lines), encoding="utf-8")
            (self.directory / (label + ".stderr.txt")).write_text("".join(errors), encoding="utf-8")
            self.save(label + ".requests.json", requests)
            self.save(label + ".results.json", results)
            self.save(label + ".command.json", {"command": command, "cwd": str(fixture["scope"]), "shell": False,
                      "vault": str(fixture["vault"]), "state_dir": env["KNOWLEDGEOS_STATE_DIR"], "import_path": env["PYTHONPATH"],
                      "pid": process.pid, "exit_code": process.returncode, "stopped": tracked["stopped"],
                      "seconds": time.monotonic() - started, "reader_threads_stopped": all(not thread.is_alive() for thread in readers),
                      "error": str(error) if error else None})
        if error is not None:
            raise error
        if process.returncode or any(thread.is_alive() for thread in readers) or len(lines) != len(events) + 1:
            raise RuntimeError("MCP process, response inventory or reader shutdown failed")
        return results

    def edit(self, fixture, action):
        vault = fixture["vault"]
        before = inventory(vault)
        if action == "edit_source":
            (vault / "Concepts/EditSeed.md").write_bytes(note("Concepts/EditSeed.md", EDITED_BODY))
        elif action == "move_target":
            (vault / "Concepts/MoveTarget.md").rename(vault / "Concepts/Archive/RenamedTarget.md")
        elif action == "repair_moved_link":
            (vault / "Concepts/MoveSeed.md").write_bytes(note("Concepts/MoveSeed.md", MOVED_BODY))
        else:
            raise ValueError("Unknown frozen editor action")
        label = "editor-" + action
        self.save(label + ".before.json", before)
        self.save(label + ".after.json", inventory(vault))
        self.mutations.append({"action": action, "before": label + ".before.json", "after": label + ".after.json"})

    def check_static(self, results, label="graph"):
        for (name, (source, expected, hops)), result in zip(CASES.items(), results):
            observed = related_observation(result, source, expected, hops, ambiguity=name == "ambiguous_basename")
            self.add_case(name, "Exact frozen neighbor paths; ambiguous references disclose the literal source, target and both candidates",
                          observed, observed["valid"], ["frozen-expectations.json", "graph.before.json", *self.evidence(label)])

    def run_journey(self):
        fixture = self.prepare_graph()
        events = [{"source": source, "hops": hops} for source, _, hops in CASES.values()]
        events += [{"source": "Concepts/EditSeed.md"}, {"source": "Concepts/EditSeed.md", "editor_action": "edit_source"},
                   {"source": "Concepts/MoveSeed.md"}, {"source": "Concepts/MoveSeed.md", "editor_action": "move_target"},
                   {"source": "Concepts/MoveSeed.md", "editor_action": "repair_moved_link"}]
        results = self.rpc_events(fixture, events)
        self.check_static(results[:len(CASES)])
        edits = [related_observation(result, "Concepts/EditSeed.md", expected) for result, expected in zip(
            results[len(CASES):len(CASES) + 2], (["Concepts/EditOld.md"], ["Concepts/EditNew.md"]))]
        self.add_case("source_edit_refresh", "A running MCP process drops the old edge and returns the new edge after an external source edit",
                      {"stages": edits, "one_mcp_pid": self.processes[-1]["pid"]}, all(row["valid"] for row in edits),
                      ["editor-edit_source.before.json", "editor-edit_source.after.json", *self.evidence("graph")])
        moves = [related_observation(result, "Concepts/MoveSeed.md", expected) for result, expected in zip(
            results[len(CASES) + 2:], (["Concepts/MoveTarget.md"], [], ["Concepts/Archive/RenamedTarget.md"]))]
        self.add_case("target_move_refresh", "The same MCP process omits a moved target, then discovers its repaired relative path without index chores",
                      {"stages": moves, "one_mcp_pid": self.processes[-1]["pid"]}, len(moves) == 3 and all(row["valid"] for row in moves),
                      ["editor-move_target.before.json", "editor-move_target.after.json", "editor-repair_moved_link.before.json", "editor-repair_moved_link.after.json", *self.evidence("graph")])
        self.preservation_case(fixture)

    def preservation_case(self, fixture):
        after = inventory(fixture["scope"])
        self.save("graph.after.json", after)
        expected = copy.deepcopy(self.scope_before)
        for relative, body in (("Concepts/EditSeed.md", EDITED_BODY), ("Concepts/MoveSeed.md", MOVED_BODY)):
            raw = note(relative, body)
            expected["vault/" + relative].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        expected["vault/Concepts/Archive/RenamedTarget.md"] = expected.pop("vault/Concepts/MoveTarget.md")
        allowed = ("vault/knowledge_index.db", "vault/.knowledgeos/index-manifest.json")
        keys = expected.keys() | after.keys()
        changed = sorted(key for key in keys if key not in allowed and expected.get(key) != after.get(key))
        observed = {"changed_except_frozen_editor_actions_and_derived_cache": changed,
                    "self_before_sha256": fixture["identity_before"], "self_after_sha256": sha(fixture["vault"] / "People/Self.md"),
                    "toolkit_unchanged": inventory(fixture["toolkit"]) == json.loads((self.directory / "cold.toolkit-before.json").read_text(encoding="utf-8")),
                    "expected_editor_actions": ["edit_source", "move_target", "repair_moved_link"], "actual_editor_actions": [row["action"] for row in self.mutations]}
        passed = not changed and observed["toolkit_unchanged"] and observed["self_before_sha256"] == observed["self_after_sha256"] and observed["actual_editor_actions"] == observed["expected_editor_actions"]
        self.add_case("source_preserved", "Complete source, unedited vault files and protected identity remain byte-identical; only three frozen editor changes and derived caches may differ",
                      observed, passed, ["cold.toolkit-before.json", "graph.before.json", "graph.after.json"])

    def process_observation(self):
        traces = {row["pid"]: row for row in (json.loads(path.read_text(encoding="utf-8")) for path in self.trace_directory.glob("*.json"))}
        direct = {row["pid"] for row in self.processes if row["role"] != "revision"}
        observed, nested, complete = set(), [], bool(direct)
        pending = list(direct)
        while pending:
            pid = pending.pop()
            if pid in observed:
                complete = False
                continue
            observed.add(pid)
            trace = traces.get(pid)
            if not isinstance(trace, dict) or trace.get("pid") != pid or not isinstance(trace.get("children"), list):
                complete = False
                continue
            for child in trace["children"]:
                valid = (isinstance(child, dict) and isinstance(child.get("pid"), int) and child.get("stopped") is True
                         and isinstance(child.get("exit_code"), int) and isinstance(child.get("argv"), list) and bool(child["argv"]))
                complete = complete and valid
                if valid:
                    nested.append(dict(child, parent_pid=pid, evidence="child-traces/" + str(pid) + ".json"))
                    if child["pid"] in traces:
                        complete = complete and traces[child["pid"]].get("parent_pid") == pid
                        pending.append(child["pid"])
        complete = complete and set(traces) == observed
        return {"nested_processes": nested, "nested_process_tracking_complete": complete,
                "traced_process_ids": sorted(traces), "trace_files": {path.relative_to(self.directory).as_posix(): sha(path) for path in self.trace_directory.glob("*.json")}}

    def finish(self, error=None):
        current = {path.relative_to(ROOT).as_posix(): sha(path) for path in source_files()}
        support = {name: sha(Path(__file__).with_name(name)) for name in self.support}
        stable = current == self.sources and sha(__file__) == self.producer_hash and support == self.support and sha(self.tracer) == self.trace_hash
        after = self.sentinels()
        processes = self.process_observation()
        stopped = bool(self.processes) and all(row["stopped"] and isinstance(row.get("exit_code"), int) for row in self.processes)
        stopped = stopped and processes["nested_process_tracking_complete"] and all(row["stopped"] for row in processes["nested_processes"])
        expected_ids = ["memory.graph." + name for name in CASE_IDS]
        complete = [row["id"] for row in self.cases] == expected_ids
        passed = complete and all(row["verdict"] == "PASS" for row in self.cases) and stable and stopped and self.before == after and error is None
        if error is not None:
            self.save("execution-error.json", {"error": str(error), "type": type(error).__name__})
        report = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "support_sha256": self.support,
                  "generated_support_sha256": {"tracer/sitecustomize.py": self.trace_hash}, "source_root": str(ROOT),
                  "revision": getattr(self, "revision", None), "platform": platform.platform(), "python": sys.version,
                  "scope": "source-only public CLI initialization and persistent public MCP graph in a complete synthetic toolkit copy",
                  "verdict": "PASS" if passed else "FAIL", "ideal_system_verdict": "NOT CHECKED", "fixed_outcome_candidate": OUTCOME,
                  "acceptance_credit_awarded": False, "expected_case_ids": expected_ids, "execution_complete": complete and error is None,
                  "product_hashes": self.sources, "product_hashes_after": current, "product_and_producer_unchanged": stable,
                  "cases": self.cases, "processes": self.processes, "all_started_processes_stopped": stopped, **processes,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after,
                                "limitation": "Selected real-vault sentinels only; not an exhaustive filesystem audit"},
                  "limits": ["No installed artifact, genuine host, owner approval, quality or longitudinal acceptance claim",
                             "Anchors resolve to note paths; no heading-existence validation or note-frontmatter alias promise",
                             "Graph calls use the default limit of thirty, with fewer than thirty expected neighbors",
                             "Nested tracking covers subprocess.Popen descendants; no native non-subprocess process-spawn audit"],
                  "error": str(error) if error else None}
        report["evidence_files"] = {path.relative_to(self.directory).as_posix(): sha(path) for path in sorted(self.directory.rglob("*"))
                                    if path.is_file() and not path.is_relative_to(self.directory / "fixtures") and path.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"],
                          "passed": sum(row["verdict"] == "PASS" for row in self.cases), "total": len(expected_ids)}), flush=True)
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError("Graph source proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return GraphRun(args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
