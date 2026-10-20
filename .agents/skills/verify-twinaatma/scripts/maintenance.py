"""Prove source maintenance, hook preservation or validation in synthetic copies."""
import argparse
import json
import os
import platform
import signal
import stat
import sys
from pathlib import Path

from data_preservation import DataRun, ROOT, inventory, operational_metadata_creation, sha, source_files

JOURNEYS = {
    "maintenance": {"producer": "verify-twinaatma.maintenance/v1", "outcome": "DATA.safe_maintenance",
                    "cases": ("ids_dry_run", "ids_write", "ids_schema", "ids_replace_fault", "ids_write_fault",
                              "ids_hardlink_self", "ids_hardlink_proposal", "ids_linked_directory", "links_write",
                              "links_replace_fault", "maps_write", "maps_edited", "maps_replace_fault")},
    "hooks": {"producer": "verify-twinaatma.hooks-preservation/v1", "outcome": "DATA.preserve_hooks",
              "cases": ("existing", "custom", "external", "linked_directory", "linked_file", "hardlinked_file", "write_fault", "chmod_fault")},
    "validation": {"producer": "verify-twinaatma.validation/v1", "outcome": "DATA.honest_validation",
                   "cases": ("good", "missing", "status", "date", "tags", "schema", "id", "duplicate", "broken", "ambiguous")},
}
MAP_OUTPUTS = ("MOCs/_MOC_Experiments.md", "MOCs/_MOC_Outcomes.md", "MOCs/_MOC_Stale_Projects.md",
               "MOCs/_MOC_Orphans.md", "MOCs/_MOC_Belief_Reviews.md", "MOCs/_MOC_Emerging_Themes.md", "MOCs/_MOC_Tensions.md")
PROTECTED = ("People/Self.md", "People/Self-Proposals/pending.md", "People/Self-Proposals/rejected.md")
DERIVED = ("vault/knowledge_index.db", "vault/.knowledgeos/index-manifest.json")


def note(title, kind="concept", identity=None):
    lines = ["---", "type: " + kind, "title: " + title, "description: Synthetic acceptance note", "status: active",
             "schema: knowledgeos-v0.2", "created: 2026-10-19", "updated: 2026-10-19", "tags: [synthetic]"]
    if identity:
        lines.append("id: " + identity)
    return ("\n".join(lines) + "\n---\n# " + title + "\n").encode()


def compare(before, after, allowed=()):
    keys = {key for key in before.keys() | after.keys() if not any(key == name or key.startswith(name + "/") for name in allowed)}
    changed = sorted(key for key in keys if before.get(key) != after.get(key))
    operational = [key for key in operational_metadata_creation(before, after) if key in changed]
    changed = [key for key in changed if key not in operational]
    result = {"unchanged": not changed, "changed": changed}
    if operational:
        result["operational_metadata_created"] = operational
    return result


def traced(operation):
    return ("import json, os, subprocess, sys\nowned_children = []\noriginal_popen = subprocess.Popen\n"
            "class ObservedPopen(original_popen):\n"
            "    def __init__(self, *args, **kwargs):\n        super().__init__(*args, **kwargs)\n"
            "        command = args[0] if args else kwargs.get('args', [])\n"
            "        owned_children.append({'process': self, 'argv': [str(part) for part in command]})\n"
            "subprocess.Popen = ObservedPopen\ntry:\n" +
            "\n".join("    " + line for line in operation.splitlines()) +
            "\nfinally:\n    for tracked in owned_children:\n        child = tracked['process']\n"
            "        if child.poll() is None:\n            child.kill()\n        child.wait()\n"
            "    rows = [{'pid': row['process'].pid, 'argv': row['argv'], 'stopped': row['process'].poll() is not None, 'exit_code': row['process'].returncode} for row in owned_children]\n"
            "    print('MAINTENANCE_CHILDREN=' + json.dumps({'parent_pid': os.getpid(), 'children': rows}), file=sys.stderr)\n")


def replace_fault(operation, target):
    return ("import os\nfrom unittest.mock import patch\noriginal_replace = os.replace\n"
            "def fail_selected(source, destination):\n"
            "    if str(destination).replace(chr(92), '/').endswith(" + repr(target) + "):\n"
            "        raise OSError('injected maintenance replace failure')\n"
            "    return original_replace(source, destination)\npatch.object(os, 'replace', fail_selected).start()\n" + operation)


def partial_fault(operation, target):
    return ("import os\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
            "original_open = Path.open\noriginal_fdopen = os.fdopen\nclass FailingWriter:\n"
            "    def __init__(self, handle):\n        self.handle = handle\n"
            "    def __enter__(self):\n        self.handle.__enter__()\n        return self\n"
            "    def __exit__(self, *args):\n        return self.handle.__exit__(*args)\n"
            "    def __getattr__(self, name):\n        return getattr(self.handle, name)\n"
            "    def write(self, payload):\n        self.handle.write(payload[:max(1, len(payload) // 2)])\n"
            "        self.handle.flush()\n        raise OSError('injected maintenance partial-write failure')\n"
            "def failed_open(path, mode='r', *args, **kwargs):\n    handle = original_open(path, mode, *args, **kwargs)\n"
            "    if 'b' in mode and any(flag in mode for flag in ('w', 'x')) and str(path).replace(chr(92), '/').endswith(" + repr(target) + "):\n"
            "        return FailingWriter(handle)\n    return handle\n"
            "def failed_fdopen(fd, mode='r', *args, **kwargs):\n    handle = original_fdopen(fd, mode, *args, **kwargs)\n"
            "    return FailingWriter(handle) if 'b' in mode and any(flag in mode for flag in ('w', 'x')) else handle\n"
            "patch.object(Path, 'open', failed_open).start()\npatch.object(os, 'fdopen', failed_fdopen).start()\n" + operation)


class MaintenanceRun(DataRun):
    def __init__(self, output, journey):
        super().__init__(output)
        self.journey = journey
        self.producer_hash = sha(__file__)
        self.support = {"data_preservation.py": sha(Path(__file__).with_name("data_preservation.py"))}
        self.nested_processes, self.nested_expectations = [], []
        self.nested_process_tracking_complete = True

    def write(self, vault, relative, raw):
        target = vault / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return target

    def prepared_fixture(self):
        scope, vault, outside = self.fixture("m" + str(len(self.cases)))
        for path, title, kind, identity in (
                ("Concepts/Launch.md", "Launch", "concept", "kos:concept:launch"),
                ("Projects/Nova.md", "Nova", "project", "kos:project:nova"),
                ("Research/Context.md", "Context", "research", "kos:research:context"),
                ("People/Self.md", "Synthetic Self", "person", None),
                ("People/Self-Proposals/pending.md", "Pending proposal", "person", None),
                ("People/Self-Proposals/rejected.md", "Rejected proposal", "person", None)):
            body = b"\nIdentity evidence [[Concepts/Launch]].\n\n```md\n[[Concepts/Launch]]\n```\n"
            self.write(vault, path, note(title, kind, identity) + (body if path in PROTECTED else b""))
        self.write(vault, "knowledgeos.config.json", b'{"schema":"knowledgeos-v0.3"}\n')
        (vault / "MOCs").mkdir(exist_ok=True)
        return scope, vault, outside

    def invoke(self, label, vault, operation):
        record, stdout, stderr = self.command(label, [sys.executable, "-B", "-c", traced(operation)], cwd=vault, vault=vault)
        traces = [line[len("MAINTENANCE_CHILDREN="):] for line in stderr.splitlines() if line.startswith("MAINTENANCE_CHILDREN=")]
        if len(traces) != 1:
            record["trace_error"] = "Nested process shutdown trace missing or duplicated"
            self.nested_process_tracking_complete = False
        else:
            trace = json.loads(traces[0])
            complete = isinstance(trace, dict) and trace.get("parent_pid") == record["pid"] and isinstance(trace.get("children"), list)
            if not complete:
                record["trace_error"] = "Nested trace has invalid parent identity or children shape"
                self.nested_process_tracking_complete = False
            else:
                for index, child in enumerate(trace["children"]):
                    self.nested_processes.append(dict(child, id=label + "-nested-" + str(index), parent_role=label,
                                                      parent_pid=record["pid"], evidence=label + ".stderr.txt",
                                                      evidence_sha256=sha(self.directory / (label + ".stderr.txt"))))
                complete = all(child.get("stopped") is True and isinstance(child.get("exit_code"), int)
                               and isinstance(child.get("argv"), list) and bool(child["argv"]) for child in trace["children"])
                self.nested_process_tracking_complete = self.nested_process_tracking_complete and complete
            self.save(label + ".nested.json", {"trace": trace, "complete": complete})
        return record, stdout, stderr

    def script(self, label, vault, name, injection=None):
        operation = "import runpy\nrunpy.run_path(" + repr("scripts/" + name) + ", run_name='__main__')"
        record, stdout, stderr = self.invoke(label, vault, injection(operation) if injection else operation)
        if name == "update_mocs.py":
            expected = ["experiment_dashboard.py"] if label == "maintenance-maps_edited" else ["experiment_dashboard.py", "outcomes_dashboard.py"]
            children = [row for row in self.nested_processes if row["parent_role"] == label]
            observed = [Path(row["argv"][1]).name if len(row["argv"]) == 2 else None for row in children]
            complete = observed == expected
            self.nested_expectations.append({"parent_role": label, "expected_scripts": expected, "observed_scripts": observed, "complete": complete})
            self.nested_process_tracking_complete = self.nested_process_tracking_complete and complete
            if not complete:
                record["trace_error"] = "Aggregator did not run the literal expected child scripts"
        return record, stdout, stderr

    def checked(self, record):
        return not record.get("error") and not record.get("trace_error") and record["stopped"]

    def snapshot(self, label, stage, scope):
        result = inventory(scope)
        self.save(label + "." + stage + ".json", result)
        return result

    def add_case(self, name, expected, observation, passed, evidence):
        self.cases.append({"id": "data." + self.journey + "." + name, "verdict": "PASS" if passed else "FAIL",
                           "expected": expected, "observed": observation, "evidence": evidence})

    def link(self, label, source, destination, directory=False):
        if directory and os.name == "nt":
            record, _, _ = self.command(label + "-junction", ["cmd", "/c", "mklink", "/J", destination, source], cwd=source.parent)
            if record["exit_code"] != 0 or not self.checked(record):
                raise OSError("Native junction creation failed")
        else:
            destination.symlink_to(source, target_is_directory=directory)

    def skip(self, name, expected, error, applicable=True):
        self.cases.append({"id": "data." + self.journey + "." + name, "verdict": "NOT CHECKED" if applicable else "NOT APPLICABLE",
                           "expected": expected, "observed": {"error": str(error)}, "evidence": []})

    def maintenance(self, name):
        label = "maintenance-" + name
        scope, vault, outside = self.prepared_fixture()
        evidence = []
        identity = {path: (vault / path).read_bytes() for path in PROTECTED}
        if name.startswith("ids_"):
            raw = note("New note") + b"\n```yaml\nid: fenced-example\nschema: fenced-example\n```\n"
            target = self.write(vault, "Inbox/Add.md", raw)
            self.write(vault, "Concepts/Held.md", note("Already held", identity="kos:concept:new-note"))
            expected_raw = raw.replace(b"type: concept\n", b"type: concept\nid: kos:concept:new-note-2\n", 1)
            if name == "ids_schema":
                raw = raw.replace(b"schema: knowledgeos-v0.2\n", b"")
                target.write_bytes(raw)
                expected_raw = raw.replace(b"type: concept\n", b"type: concept\nid: kos:concept:new-note-2\n", 1).replace(b"\n---\n# ", b"\nschema: knowledgeos-v0.2\n---\n# ", 1)
            if name in ("ids_hardlink_self", "ids_hardlink_proposal"):
                target.rename(target.with_suffix(".original"))
                protected = PROTECTED[0] if name.endswith("self") else PROTECTED[1]
                os.link(vault / protected, target)
            if name == "ids_linked_directory":
                self.write(outside, "External.md", note("External synthetic note"))
                try:
                    self.link(label, outside, vault / "LinkedNotes", directory=True)
                except OSError as error:
                    self.skip(name, "Actual native linked-note directory is excluded", error)
                    return
            args = ["ids", "assign", "--vault", str(vault)] + ([] if name == "ids_dry_run" else ["--write"])
            operation = "from knowledgeos.__main__ import main\nraise SystemExit(main(" + repr(args) + "))"
            if name == "ids_replace_fault":
                operation = replace_fault(operation, "Inbox/Add.md")
            elif name == "ids_write_fault":
                operation = partial_fault(operation, "Inbox/Add.md")
            before = self.snapshot(label, "before", scope)
            record, stdout, stderr = self.invoke(label, vault, operation)
            after = self.snapshot(label, "after", scope)
            refusal = name in ("ids_replace_fault", "ids_write_fault", "ids_hardlink_self", "ids_hardlink_proposal")
            writable = name != "ids_dry_run" and not refusal
            compared = compare(before, after, ["vault/Inbox/Add.md"] if writable else [])
            try:
                result = json.loads(stdout)
            except ValueError:
                result = {}
            literal = target.read_bytes() == expected_raw if writable else True
            changes = [{"path": "Inbox/Add.md", "old_id": "", "new_id": "kos:concept:new-note-2", "written": writable}]
            observation = dict(compared, exit_code=record["exit_code"], result=result, literal_note_bytes_match=literal,
                               identity_evidence_unchanged=all((vault / path).read_bytes() == raw for path, raw in identity.items()))
            injected = not name.endswith("fault") or "injected maintenance " in stderr
            observation["fault_injected"] = injected
            passed = (self.checked(record) and compared["unchanged"] and observation["identity_evidence_unchanged"] and injected
                      and ((record["exit_code"] != 0 and bool(stderr.strip())) if refusal else
                           (record["exit_code"] == 0 and literal and result.get("changes") == changes)))
            expected = "Literal ID/schema addition or dry-run changes; only the named note changes; identity, proposals, outside links and faulted originals stay exact"
        elif name.startswith("links_"):
            self.write(vault, "Concepts/Target.md", note("Target", identity="kos:concept:target"))
            self.write(vault, "Other/Target.md", note("Other target", identity="kos:concept:other-target"))
            raw = (b"Keep\r\n```md\n[[Concepts/Target]]\n```\r\n~~~md\n[[Concepts/Target]]\n~~~\n"
                   b"`[[Concepts/Target]]`\r\n[[Target]]\n[[Concepts/Target|Named]]\n"
                   b"[moving](old/Launch.md#anchor)\n[web](https://example.invalid/Target.md)\n")
            target = self.write(vault, "Inbox/Add.md", raw)
            expected_raw = raw.replace(b"[[Concepts/Target|Named]]\n", b"[Named](../Concepts/Target.md)\n").replace(b"(old/Launch.md#anchor)", b"(../Concepts/Launch.md#anchor)")
            self.write(vault, "knowledge_index.db", b"")
            before = self.snapshot(label, "before", scope)
            injection = (lambda operation: replace_fault(operation, "Inbox/Add.md")) if name.endswith("fault") else None
            record, stdout, stderr = self.script(label, vault, "refactor_links.py", injection)
            after = self.snapshot(label, "after", scope)
            refusal = name.endswith("fault")
            compared = compare(before, after, [] if refusal else ["vault/Inbox/Add.md"])
            literal = target.read_bytes() == (raw if refusal else expected_raw)
            observation = dict(compared, exit_code=record["exit_code"], literal_note_bytes_match=literal,
                               identity_evidence_unchanged=all((vault / path).read_bytes() == raw for path, raw in identity.items()))
            passed = (self.checked(record) and compared["unchanged"] and literal and observation["identity_evidence_unchanged"]
                      and ((record["exit_code"] != 0 and "injected maintenance replace failure" in stderr) if refusal else record["exit_code"] == 0))
            expected = "Unique links migrate literally; ambiguous links, fenced/inline examples and identity stay exact; replace failure preserves originals"
        else:
            self.write(vault, "Experiments/Active.md", note("Literal active experiment", "experiment", "kos:experiment:literal-active"))
            init, _, error = self.invoke(label + "-index", vault, "from knowledgeos.indexer import rebuild_index\nrebuild_index('.')")
            if init["exit_code"] != 0:
                raise RuntimeError("Map fixture index failed: " + error)
            if name == "maps_edited":
                self.write(vault, MAP_OUTPUTS[0], b"USER MAP EDIT\r\n")
            if name == "maps_replace_fault":
                initial, _, error = self.script(label + "-initial", vault, "update_mocs.py")
                if initial["exit_code"] != 0:
                    raise RuntimeError("Initial map fixture generation failed: " + error)
                self.write(vault, "Projects/Old.md", note("Literal stale project", "project", "kos:project:literal-stale").replace(b"updated: 2026-10-19", b"updated: 2020-01-01"))
                refreshed, _, error = self.invoke(label + "-changed-index", vault, "from knowledgeos.indexer import rebuild_index\nrebuild_index('.')")
                if refreshed["exit_code"] != 0:
                    raise RuntimeError("Changed map fixture index failed: " + error)
            before = self.snapshot(label, "before", scope)
            injection = (lambda operation: replace_fault(operation, MAP_OUTPUTS[2])) if name.endswith("fault") else None
            record, stdout, stderr = self.script(label, vault, "update_mocs.py", injection)
            after = self.snapshot(label, "after", scope)
            writable = name == "maps_write"
            allowed = ["vault/" + path for path in MAP_OUTPUTS] + ["vault/.knowledgeos/generated"] if writable else ["vault/.knowledgeos/generated"] if name.endswith("fault") else []
            compared = compare(before, after, allowed + list(DERIVED))
            outputs = {path: {"exists": (vault / path).is_file(), "text": (vault / path).read_bytes().decode("utf-8") if (vault / path).is_file() else None} for path in MAP_OUTPUTS}
            usable = writable and all(row["exists"] and row["text"].startswith("---\n") and "\n# " in row["text"] for row in outputs.values()) and "Literal active experiment" in outputs[MAP_OUTPUTS[0]]["text"]
            observation = dict(compared, exit_code=record["exit_code"], outputs=outputs, literal_content_visible=usable,
                               identity_evidence_unchanged=all((vault / path).read_bytes() == raw for path, raw in identity.items()),
                               derived_state_changes=[path for path in DERIVED if before.get(path) != after.get(path)])
            passed = (self.checked(record) and compared["unchanged"] and observation["identity_evidence_unchanged"] and
                      ((record["exit_code"] == 0 and usable) if writable else record["exit_code"] != 0))
            if name.endswith("fault"):
                passed = passed and "injected maintenance replace failure" in stderr
            if writable:
                repeated, _, _ = self.script(label + "-repeat", vault, "update_mocs.py")
                repeated_inventory = self.snapshot(label, "repeat", scope)
                observation["repeat"] = {"exit_code": repeated["exit_code"], **compare(after, repeated_inventory, DERIVED)}
                passed = passed and self.checked(repeated) and repeated["exit_code"] == 0 and observation["repeat"]["unchanged"]
                evidence += [label + "-repeat" + suffix for suffix in (".command.json", ".stdout.txt", ".stderr.txt")] + [label + ".repeat.json"]
            expected = "All seven map outputs reflect literal source evidence; edits and failed replacement preserve originals; repeat is idempotent"
        evidence += [label + suffix for suffix in (".before.json", ".after.json", ".command.json", ".stdout.txt", ".stderr.txt")]
        self.add_case(name, expected, observation, passed, evidence)

    def hooks(self, name):
        label = "hooks-" + name
        scope, vault, outside = self.prepared_fixture()
        init, _, error = self.command(label + "-git-init", ["git", "init", "--quiet", vault], cwd=vault, vault=vault)
        if init["exit_code"] != 0:
            raise RuntimeError("Synthetic Git initialization failed: " + error)
        hook = vault / ".git/hooks/pre-commit"
        if name == "existing":
            hook.write_bytes(b"#!/bin/sh\necho USER HOOK\nexit 0\n")
        elif name in ("custom", "external", "linked_directory"):
            location = ".custom-hooks" if name == "custom" else str(outside) if name == "external" else ".linked-hooks"
            config, _, error = self.command(label + "-git-config", ["git", "-C", vault, "config", "core.hooksPath", location], cwd=vault, vault=vault)
            if config["exit_code"] != 0:
                raise RuntimeError("Custom hook fixture failed: " + error)
            if name == "custom":
                hook = vault / ".custom-hooks/pre-commit"
            elif name == "linked_directory":
                try:
                    self.link(label, outside, vault / ".linked-hooks", directory=True)
                except OSError as caught:
                    self.skip(name, "Actual native linked hook directory is refused", caught)
                    return
        elif name in ("linked_file", "hardlinked_file"):
            try:
                if name == "linked_file":
                    self.link(label, outside / "sentinel.bin", hook)
                else:
                    os.link(outside / "sentinel.bin", hook)
            except OSError as caught:
                self.skip(name, "Actual native linked or hardlinked hook file is refused", caught)
                return
        if name == "chmod_fault" and os.name != "posix":
            self.skip(name, "POSIX chmod failure is measured on POSIX", "Windows uses Git for Windows shell hooks", applicable=False)
            return
        before = self.snapshot(label, "before", scope)
        injection = None
        if name == "write_fault":
            injection = lambda operation: partial_fault(operation, "pre-commit")
        elif name == "chmod_fault":
            injection = lambda operation: "import os\nfrom unittest.mock import patch\npatch.object(os, 'chmod', side_effect=OSError('injected hook chmod failure')).start()\n" + operation
        record, stdout, stderr = self.script(label, vault, "setup_git_hooks.py", injection)
        after = self.snapshot(label, "after", scope)
        allowed = ["vault/.custom-hooks"] if name == "custom" else ["vault/.git/hooks/pre-commit"] if name == "chmod_fault" else []
        compared = compare(before, after, allowed)
        observation = dict(compared, exit_code=record["exit_code"], installed_hook_present=hook.is_file(),
                           success_claim="setup successfully" in stdout.lower())
        passed = self.checked(record) and compared["unchanged"]
        evidence = [label + suffix for suffix in (".before.json", ".after.json", ".command.json", ".stdout.txt", ".stderr.txt")]
        if name == "custom":
            payload = hook.read_bytes() if hook.is_file() else b""
            plain = hook.is_file() and not hook.is_symlink() and hook.stat().st_nlink == 1
            observation["hook_sha256"] = sha(hook) if hook.is_file() else None
            observation["hook_declares_validator"] = b"scripts/validate_schema.py" in payload and payload.startswith(b"#!/bin/sh\n")
            observation["native_executable"] = bool(hook.stat().st_mode & stat.S_IXUSR) if os.name == "posix" and hook.is_file() else None
            repeated, _, _ = self.script(label + "-repeat", vault, "setup_git_hooks.py")
            repeat_after = self.snapshot(label, "repeat", scope)
            observation["repeat"] = {"exit_code": repeated["exit_code"], **compare(after, repeat_after)}
            executed, run_stdout, run_stderr = self.command(label + "-run", ["git", "-C", vault, "hook", "run", "pre-commit"], cwd=vault, vault=vault)
            hook_output = run_stdout + run_stderr
            ran_after = self.snapshot(label, "ran", scope)
            observation["execution"] = {"exit_code": executed["exit_code"], "validator_message": "Running KnowledgeOS pre-commit schema validation..." in hook_output,
                                        "summary_visible": '"errors": 0' in hook_output, **compare(repeat_after, ran_after)}
            passed = (passed and record["exit_code"] == 0 and plain and observation["hook_declares_validator"]
                      and (os.name != "posix" or observation["native_executable"])
                      and self.checked(repeated) and repeated["exit_code"] == 0 and observation["repeat"]["unchanged"]
                      and self.checked(executed) and executed["exit_code"] == 0 and observation["execution"]["validator_message"]
                      and observation["execution"]["summary_visible"] and observation["execution"]["unchanged"])
            evidence += [label + suffix for suffix in (".repeat.json", ".ran.json")]
            evidence += [label + step + suffix for step in ("-repeat", "-run") for suffix in (".command.json", ".stdout.txt", ".stderr.txt")]
        else:
            passed = passed and record["exit_code"] != 0 and not observation["success_claim"] and bool(stderr.strip())
            if name == "write_fault":
                passed = passed and "injected maintenance partial-write failure" in stderr
            elif name == "chmod_fault":
                passed = passed and "injected hook chmod failure" in stdout + stderr
                observation["retained_unexecutable_hook"] = hook.is_file() and not bool(hook.stat().st_mode & stat.S_IXUSR)
        self.add_case(name, "Existing hooks and source data stay exact; contained custom hook is runnable and idempotent; failures return nonzero without false success", observation, passed, evidence)

    def validation(self, name):
        label = "validation-" + name
        scope, vault, outside = self.prepared_fixture()
        target = self.write(vault, "Inbox/Probe.md", note("Probe", identity="kos:concept:probe") +
                            b"\n[[Concepts/Launch]]\n[attachment](../Assets/map.bin)\n```md\n[[DoesNotExist]]\n```\n")
        expected = []
        if name == "missing":
            target.write_bytes(target.read_bytes().replace(b"description: Synthetic acceptance note\n", b""))
            expected = [{"path": "Inbox/Probe.md", "issue": "missing_required_fields", "fields": ["description"]}]
        elif name == "status":
            target.write_bytes(target.read_bytes().replace(b"status: active", b"status: impossible"))
            expected = [{"path": "Inbox/Probe.md", "issue": "invalid_status", "status": "impossible"}]
        elif name == "date":
            target.write_bytes(target.read_bytes().replace(b"created: 2026-10-19", b"created: 2026-02-30"))
            expected = [{"path": "Inbox/Probe.md", "issue": "invalid_date", "field": "created", "value": "2026-02-30"}]
        elif name == "tags":
            target.write_bytes(target.read_bytes().replace(b"tags: [synthetic]", b"tags: scalar"))
            expected = [{"path": "Inbox/Probe.md", "issue": "invalid_tags", "tags": "scalar"}]
        elif name == "schema":
            target.write_bytes(target.read_bytes().replace(b"schema: knowledgeos-v0.2", b"schema: impossible-schema"))
            expected = [{"path": "Inbox/Probe.md", "issue": "unknown_schema_version", "schema": "impossible-schema"}]
        elif name == "id":
            target.write_bytes(target.read_bytes().replace(b"id: kos:concept:probe", b"id: invalid id"))
            expected = [{"path": "Inbox/Probe.md", "issue": "invalid_id_format", "id": "invalid id"}]
        elif name == "duplicate":
            self.write(vault, "Inbox/ZDuplicate.md", note("Duplicate", identity="kos:concept:probe"))
            expected = [{"path": "Inbox/ZDuplicate.md", "issue": "duplicate_id", "id": "kos:concept:probe", "other": "Inbox/Probe.md"}]
        elif name == "broken":
            target.write_bytes(target.read_bytes() + b"\n[[NoSuchNote]]\n")
            expected = [{"path": "Inbox/Probe.md", "issue": "broken_link", "target": "NoSuchNote"}]
        elif name == "ambiguous":
            self.write(vault, "Other/Launch.md", note("Other launch", identity="kos:concept:other-launch"))
            target.write_bytes(target.read_bytes() + b"\n[[Launch]]\n")
            expected = [{"path": "Inbox/Probe.md", "issue": "ambiguous_link", "target": "Launch", "candidates": ["Concepts/Launch.md", "Other/Launch.md"]}]
        before = self.snapshot(label, "before", scope)
        records, observations = [], []
        operations = (("-cli", "from knowledgeos.__main__ import main\nraise SystemExit(main(" + repr(["validate", "--vault", str(vault)]) + "))"),
                      ("-script", "import runpy, sys\nsys.argv = ['validate_schema.py', '--vault', " + repr(str(vault)) + "]\nrunpy.run_path('scripts/validate_schema.py', run_name='__main__')"))
        for suffix, operation in operations:
            record, stdout, _ = self.invoke(label + suffix, vault, operation)
            records.append(record)
            try:
                result = json.loads(stdout)
            except ValueError:
                result = {}
            observations.append({"exit_code": record["exit_code"], "errors": result.get("errors"), "warnings": result.get("warnings"),
                                 "notes_checked": result.get("notes_checked"), "summary": result.get("summary")})
        after = self.snapshot(label, "after", scope)
        compared = compare(before, after)
        expected_count = 7 + (name in ("duplicate", "ambiguous"))
        passed = compared["unchanged"] and all(self.checked(record) for record in records)
        for result in observations:
            valid = (isinstance(result["warnings"], list) and result["errors"] == expected
                     and result["exit_code"] == (0 if name == "good" else 1) and result["notes_checked"] == expected_count
                     and result["summary"] == {"errors": len(expected), "warnings": len(result["warnings"])})
            passed = passed and valid
        observation = dict(compared, entrypoints=observations, literal_expected_errors=expected, literal_expected_notes=expected_count)
        evidence = [label + suffix for suffix in (".before.json", ".after.json")]
        evidence += [label + step + suffix for step in ("-cli", "-script") for suffix in (".command.json", ".stdout.txt", ".stderr.txt")]
        self.add_case(name, "Both public validation entrypoints return exact diagnostics and exit status without writing any source entry", observation, passed, evidence)

    def run_case(self, name):
        getattr(self, self.journey)(name)

    def finish(self, error=None):
        after = self.sentinels()
        current = {path.relative_to(ROOT).as_posix(): sha(path) for path in source_files()}
        stable = current == self.sources and sha(__file__) == self.producer_hash and self.support == {name: sha(Path(__file__).with_name(name)) for name in self.support}
        stopped = (bool(self.processes) and all(process["stopped"] for process in self.processes)
                   and self.nested_process_tracking_complete and all(process["stopped"] for process in self.nested_processes))
        definition = JOURNEYS[self.journey]
        expected_ids = {"data." + self.journey + "." + name for name in definition["cases"]}
        complete = {case["id"] for case in self.cases} == expected_ids and len(self.cases) == len(expected_ids)
        acceptable = all(case["verdict"] == "PASS" or (case["id"] == "data.hooks.chmod_fault" and os.name != "posix" and case["verdict"] == "NOT APPLICABLE") for case in self.cases)
        if error:
            self.save("execution-error.json", {"error": repr(error)})
        report = {"producer": definition["producer"], "producer_sha256": self.producer_hash, "support_sha256": self.support,
                  "source_root": str(ROOT), "revision": getattr(self, "revision", None), "platform": platform.platform(), "python": sys.version,
                  "scope": "source-only " + self.journey + " public entrypoints in complete synthetic toolkit copies",
                  "fixed_outcome_candidate": definition["outcome"], "acceptance_credit_awarded": False, "ideal_system_verdict": "NOT CHECKED",
                  "verdict": "PASS" if complete and acceptable and stable and stopped and self.before == after and not error else "FAIL",
                  "product_hashes": self.sources, "product_hashes_after": current, "product_and_producer_unchanged": stable,
                  "cases": self.cases, "processes": self.processes, "all_started_processes_stopped": stopped,
                  "nested_processes": self.nested_processes, "nested_expectations": self.nested_expectations,
                  "nested_process_tracking_complete": self.nested_process_tracking_complete,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after,
                                "limitation": "Selected real-vault sentinels only; not an exhaustive filesystem audit"},
                  "limitations": ["No installed-package, host, privacy, backup restore or owner approval acceptance",
                                  "POSIX chmod cannot be certified on Windows; unsupported native links remain NOT CHECKED",
                                  "ID assignment is the additive schema-stamping entrypoint; no broader schema migration claim",
                                  "Per-output preservation only; no multi-file transaction claim"], "error": repr(error) if error else None}
        report["evidence_files"] = {path.name: sha(path) for path in sorted(self.directory.iterdir()) if path.is_file() and path.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"],
                          "passed": sum(case["verdict"] == "PASS" for case in self.cases), "total": len(expected_ids)}))
        return 0 if report["verdict"] == "PASS" else 1

    def run(self):
        error = None
        try:
            _, output, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            self.revision = output.strip()
            for name in JOURNEYS[self.journey]["cases"]:
                self.run_case(name)
        except BaseException as caught:
            error = caught
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journey", required=True, choices=JOURNEYS)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError("Maintenance proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return MaintenanceRun(args.output, args.journey).run()


if __name__ == "__main__":
    raise SystemExit(main())
