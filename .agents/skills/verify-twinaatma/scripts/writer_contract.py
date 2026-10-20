"""Literal public operations for the single identity-preservation outcome."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath

from physical_observer import PROTECTED_IO_OBSERVER

PRODUCER = "verify-twinaatma.identity-writers/v1"
OUTCOME = "IDENTITY.all_writers_preserve"
SCOPE = "source-only complete alternative-writer identity preservation"
SESSION = "identity-writer-session-41"
CAPTURE_ID = "identity-writer-capture-41"
CAPTURE_NAME = "Inbox/capture-" + hashlib.sha256(CAPTURE_ID.encode()).hexdigest() + ".md"
PATCH = "- Synthetic writer preference IW41. Review retained evidence before changing a preference."
HISTORY = {
    "pending": {"summary": "Synthetic retained pending IW41", "section": "heuristics", "proposed_markdown": "- Retained pending preference IW41 needs human review.", "mode": "append"},
    "rejected": {"summary": "Synthetic retained rejected IW42", "section": "heuristics", "proposed_markdown": "- Retained rejected preference IW42 needs human review.", "mode": "append"},
}
NOTE = ("---\ntype: concept\ntitle: Identity writer source\ndescription: Synthetic source preservation probe\n"
        "schema: knowledgeos-v0.2\nstatus: active\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [synthetic]\n"
        "id: kos:concept:writer-source\n---\n# Identity writer source\nThe prototype review happens after one reversible trial.\n")
FORGET = NOTE.replace("Identity writer source", "Forgetting source").replace("kos:concept:writer-source", "kos:concept:forget-source").replace("The prototype review happens after one reversible trial.", "A synthetic canceled comparison is no longer useful to this fixture.")
OLD = NOTE.replace("Identity writer source", "Prior comparison").replace("kos:concept:writer-source", "kos:concept:old-source").replace("The prototype review happens after one reversible trial.", "The old synthetic delivery estimate was three days.")
NEW = NOTE.replace("Identity writer source", "Current comparison").replace("kos:concept:writer-source", "kos:concept:new-source").replace("The prototype review happens after one reversible trial.", "The reviewed synthetic delivery estimate is five days.")
DECISION = NOTE.replace("type: concept", "type: decision").replace("Identity writer source", "Reviewed writer decision").replace("kos:concept:writer-source", "kos:decision:writer-review").replace("status: active", "status: active\noutcome_status: pending")
OUTCOME_ARGS = {"path": "Decisions/Review.md", "expected_sha256": hashlib.sha256(DECISION.encode()).hexdigest(),
                "outcome_status": "confirmed", "actual_outcome": "The isolated prototype finished within the reviewed time.",
                "lesson": "Use one contained prototype before revising a general preference."}
FIXTURE_NOTES = {"Concepts/Source.md": NOTE, "Concepts/Forget.md": FORGET,
                 "Concepts/Old.md": OLD, "Concepts/New.md": NEW, "Decisions/Review.md": DECISION}
for suffix, outcome in (("a", "The first contained review found the missing assumption."), ("b", "The second contained review kept the comparison reversible.")):
    FIXTURE_NOTES["Decisions/Drift-" + suffix.upper() + ".md"] = (
        DECISION.replace("Reviewed writer decision", "Corroborated writer decision " + suffix)
        .replace("kos:decision:writer-review", "kos:decision:writer-drift-" + suffix)
        .replace("outcome_status: pending", "outcome_status: confirmed\nactual_outcome: " + outcome +
                 "\nlesson: Choose the contained review before the larger review.\nbelief_before: Choose the larger review first.\nbelief_after: Choose the contained review before the larger review."))
SHELL_OBSERVER = (
    "printf 'IDENTITY_NATIVE_SHELL_START={\"pid\":%s,\"parent_pid\":%s,\"script\":\"%s\"}\\n' \"${BASHPID}\" \"${PPID}\" \"$0\" >&2\n"
    "trap 'writer_shell_code=$?; printf '\"'\"'IDENTITY_NATIVE_SHELL_EXIT={\"pid\":%s,\"exit_code\":%s}\\n'\"'\"' \"${BASHPID}\" \"${writer_shell_code}\" >&2' EXIT\n"
    'python() { "${WRITER_PYTHON}" -B -P -c "${WRITER_SCRIPT_RUNNER}" "$@"; }\nexport -f python\n'
)
RUNTIME_OBSERVER = (
    "import json as _writer_json, os as _writer_os, sys as _writer_sys\n"
    "from pathlib import Path as _WriterPath\n"
    "print('IDENTITY_RUNTIME_START=' + _writer_json.dumps({'pid': _writer_os.getpid(), 'parent_pid': _writer_os.getppid(), "
    "'argv': list(_writer_sys.orig_argv), 'observer': str(_WriterPath(__file__).absolute())}), file=_writer_sys.stderr)\n"
) + PROTECTED_IO_OBSERVER
SHELL_RUNNER = (
    "import json, os, runpy, sys\nfrom pathlib import Path\n"
    "original = sys.argv[1:]\nactual = [part.decode() for part in Path('/proc/self/cmdline').read_bytes().split(bytes([0])) if part]\n"
    "print('IDENTITY_SHELL_CHILD_START=' + json.dumps({'pid': os.getpid(), 'parent_pid': os.getppid(), 'argv': actual, 'operation_argv': original}), file=sys.stderr)\n"
    "code = 0\nsys.argv = original\ntry:\n    runpy.run_path(original[0], run_name='__main__')\n"
    "except SystemExit as error:\n    code = int(error.code or 0) if isinstance(error.code, (int, type(None))) else 1\n    raise\n"
    "except BaseException:\n    code = 1\n    raise\nfinally:\n"
    "    print('IDENTITY_SHELL_CHILD_EXIT=' + json.dumps({'pid': os.getpid(), 'exit_code': code}), file=sys.stderr)\n"
)


def normal_calls():
    return [
        ("memory_self_get", {}),
        ("memory_search", {"query": "prototype review", "limit": 8}),
        ("memory_related", {"path_or_id": "Concepts/Source.md", "hops": 1, "limit": 8}),
        ("memory_get_note", {"path_or_id": "Concepts/Source.md"}),
        ("memory_decisions", {}), ("memory_drift", {"days": 30}),
        ("memory_timeline", {"days": 30}),
        ("memory_bootstrap_context", {"task_hint": "review the synthetic prototype", "limit": 8}),
        ("memory_pending_outcomes", {}), ("memory_list_self_proposals", {}), ("memory_ops_status", {}),
        ("memory_session_start", {"task_hint": "writer preservation IW41", "session_id": SESSION}),
        ("memory_breathe", {"task_hint": "writer preservation IW41", "session_id": SESSION}),
        capture_call(),
        ("memory_propose_note_update", {"path_or_id": "Concepts/Source.md", "summary": "Review the ordinary note", "patch_markdown": "A proposed ordinary note edit needs review."}),
        ("memory_propose_self_update", {"summary": "Writer proposal IW41", "section": "heuristics", "proposed_markdown": PATCH, "mode": "append"}),
        ("memory_record_outcome", OUTCOME_ARGS),
        ("memory_propose_from_lesson", {"path_or_id": "Decisions/Review.md"}),
        ("memory_propose_from_drift", {"days": 30}),
        ("memory_supersede", {"path_or_id": "Concepts/Old.md", "expected_sha256": hashlib.sha256(OLD.encode()).hexdigest(),
                              "replacement_path_or_id": "Concepts/New.md", "replacement_sha256": hashlib.sha256(NEW.encode()).hexdigest()}),
        ("memory_forget", {"path_or_id": "Concepts/Forget.md", "expected_sha256": hashlib.sha256(FORGET.encode()).hexdigest()}),
        ("memory_session_end", {"summary": "A synthetic writer verification retained the unchanged identity and reviewed source evidence.",
                                "capture_title": "Writer session IW41", "session_id": SESSION}),
    ]


def capture_call():
    return ("memory_capture", {"title": "Writer capture IW41", "content": "One contained synthetic capture.", "request_id": CAPTURE_ID})


def proposal_call():
    return ("memory_propose_self_update", {"summary": "Writer proposal IW41", "section": "heuristics", "proposed_markdown": PATCH, "mode": "append"})


def forget_call():
    return ("memory_forget", {"path_or_id": "Concepts/Forget.md", "expected_sha256": hashlib.sha256(FORGET.encode()).hexdigest()})


def alias_specs():
    specs = [
        {"id": "capture-target", "path": "vault/" + CAPTURE_NAME, "call": capture_call()},
        {"id": "outcome-source", "path": "vault/Decisions/Alias.md", "call": ("memory_record_outcome", dict(OUTCOME_ARGS, path="Decisions/Alias.md"))},
        {"id": "autopilot-state", "path": "vault/.knowledgeos/autopilot.json", "call": ("memory_session_start", {"session_id": SESSION})},
        {"id": "index-manifest", "path": "vault/.knowledgeos/index-manifest.json", "call": ("memory_session_start", {"session_id": SESSION})},
        {"id": "remembering-policy", "path": "vault/.knowledgeos/remembering-policy.json", "call": forget_call()},
        {"id": "sessions-lock", "path": "vault/.knowledgeos/sessions.lock", "call": ("memory_session_start", {"session_id": SESSION})},
        {"id": "sessions-guard", "path": "vault/.knowledgeos/sessions.lock.guard", "call": ("memory_session_start", {"session_id": SESSION})},
        {"id": "capture-lock", "path": "vault/.knowledgeos/capture.lock", "call": capture_call()},
        {"id": "capture-guard", "path": "vault/.knowledgeos/capture.lock.guard", "call": capture_call()},
        {"id": "index-lock", "path": "vault/.knowledgeos/index-rebuild.lock", "call": ("memory_session_start", {"session_id": SESSION})},
        {"id": "index-guard", "path": "vault/.knowledgeos/index-rebuild.lock.guard", "call": ("memory_session_start", {"session_id": SESSION})},
    ]
    for suffix in ("", "-wal", "-shm", "-journal"):
        specs.append({"id": "database" + (suffix or "-main"), "path": "vault/knowledge_index.db" + suffix,
                      "call": ("memory_search", {"query": "prototype", "limit": 8})})
    return specs


def directory_specs():
    return [
        {"id": "inbox", "path": "vault/Inbox", "calls": [capture_call(), ("memory_propose_note_update", {"path_or_id": "Concepts/Source.md", "summary": "Alias note probe", "patch_markdown": "Synthetic proposed edit."})]},
        {"id": "proposal-directory", "path": "vault/People/Self-Proposals", "calls": [proposal_call()]},
        {"id": "state-directory", "path": "vault/.knowledgeos", "calls": [("memory_session_start", {"session_id": SESSION}), forget_call()]},
    ]


def encoded_calls(calls):
    return json.dumps(calls, ensure_ascii=False, separators=(",", ":"))


def public_operation(arguments):
    return "from knowledgeos.__main__ import main\nraise SystemExit(main(" + repr(list(arguments)) + "))"


def fault_operation(operation, destination):
    return ("import os, sys\nfrom unittest.mock import patch\noriginal_replace = os.replace\n"
            "def failed_replace(source, target):\n"
            "    if str(target).replace(chr(92), '/').endswith(" + repr(destination) + "):\n"
            "        print('IDENTITY_WRITER_FAULT=' + str(target), file=sys.stderr)\n"
            "        raise OSError('injected identity writer replace failure')\n"
            "    return original_replace(source, target)\n"
            "patch.object(os, 'replace', failed_replace).start()\n" + operation)


def native_join(base, *parts):
    return str((PurePosixPath(base) if str(base).startswith("/") else PureWindowsPath(base)).joinpath(*parts))


def cli_arguments(name, fixture):
    vault, scope = str(fixture["vault"]), str(fixture["scope"])
    ordinary = {
        "cli-capture": ["memory", "memory_capture", "--vault", vault, "--args", json.dumps({"title": "CLI writer IW41", "content": "A synthetic CLI capture preserves identity."})],
        "cli-breathe": ["breathe", "--vault", vault, "--task-hint", "writer preservation"],
        "cli-hook-end": ["hook", "twin_session_end", "--vault", vault],
        "cli-hook-start": ["hook", "twin_session_start", "--vault", vault],
        "cli-self-summary": ["self", "summary", "--vault", vault],
        "cli-self-pending": ["self", "pending", "--vault", vault],
        "init-refresh": ["init", vault, "--name", "Another synthetic supplied name", "--force", "--non-interactive"],
        "setup-out-existing-self": ["setup-host", "--host", "cursor", "--vault", vault, "--out", native_join(vault, "People/Self.md")],
        "setup-out-new": ["setup-host", "--host", "cursor", "--vault", vault, "--out", native_join(scope, "new-host.json")],
        "legacy-outcome": ["memory", "memory_record_outcome", "--vault", vault, "--args", json.dumps(OUTCOME_ARGS)],
    }
    for host in ("cursor", "vscode", "codex"):
        ordinary["setup-" + host] = ordinary["hard-setup-" + host] = ordinary["symlink-setup-" + host] = ["setup-host", "--host", host, "--vault", vault, "--write"]
    for prefix, (tool, args) in {"capture-fault": capture_call(), "outcome-fault": ("memory_record_outcome", OUTCOME_ARGS), "policy-fault": forget_call()}.items():
        ordinary[prefix] = ordinary[prefix + "-retry"] = ["memory", tool, "--vault", vault, "--args", json.dumps(args)]
    ordinary["setup-fault"] = ordinary["setup-fault-retry"] = ["setup-host", "--host", "cursor", "--vault", vault, "--write"]
    if name not in ordinary:
        raise ValueError("Unspecified public CLI writer case: " + name)
    return ordinary[name]


def legacy_specs(fixture):
    vault = str(fixture["vault"])
    return [
        ("script-rebuild_index-0", "scripts/rebuild_index.py", ["--vault", vault]),
        ("script-propose_self_update-0", "scripts/propose_self_update.py", ["--vault", vault, "manual", "--section", "heuristics", "--summary", "Source wrapper IW41", "--markdown", "- Synthetic rule HX41. Compare one reversible option before choosing.\n- Synthetic rule HX42. Record evidence before generalizing.\n- Synthetic source wrapper needs review."]),
        ("script-propose_self_update-1", "scripts/propose_self_update.py", ["--vault", vault, "from-drift", "--days", "30"]),
        ("script-intelligence_brief-0", "scripts/intelligence_brief.py", ["--vault", vault]),
        ("script-learning_trajectory-0", "scripts/learning_trajectory.py", ["--vault", vault]),
        ("script-onboarding-0", "scripts/onboarding.py", []),
        ("script-search-0", "scripts/search.py", ["prototype"]),
        ("script-daily_capture_report-0", "scripts/daily_capture_report.py", []),
        ("script-weekly_data-0", "scripts/weekly_data.py", []),
        ("script-refinement_report-0", "scripts/refinement_report.py", []),
        ("script-check_alignment-0", "scripts/check_alignment.py", []),
        ("script-smoke_test-0", "scripts/smoke_test.py", []),
        ("hook-start-script", ".cursor/hooks/twin_session_start.py", []),
        ("hook-end-script", ".cursor/hooks/twin_session_end.py", []),
        ("script-propose_self_update-2", "scripts/propose_self_update.py", ["--vault", vault, "from-lesson", "Decisions/Review.md"]),
    ]


def expected_case_ids(os_name):
    normal = {"normal-tools", "normal-reject", "cli-capture", "cli-breathe", "cli-hook-end", "cli-hook-start", "cli-self-summary", "cli-self-pending", "init-refresh",
              "setup-cursor", "setup-vscode", "setup-codex", "setup-out-existing-self", "setup-out-new", "capture-first", "capture-collision",
              "outcome-protected-self", "memory_forget-self", "memory_supersede-self"}
    normal |= {"hard-" + s["id"] for s in alias_specs()}
    normal |= {"directory-" + s["id"] for s in directory_specs()}
    normal |= {"hard-setup-" + host for host in ("cursor", "vscode", "codex")}
    normal |= {name for name, _, _ in legacy_specs({"vault": "V"})}
    normal |= {"legacy-outcome", "script-propose_self_update-3"}
    normal |= {name + suffix for name in ("capture-fault", "outcome-fault", "policy-fault", "setup-fault") for suffix in ("", "-retry")}
    if os_name == "posix":
        normal |= {"symlink-" + spec["id"] for spec in alias_specs()}
        normal |= {"symlink-setup-" + host for host in ("cursor", "vscode", "codex")}
        normal |= {"shell-" + name for name in ("rebuild_index", "capture", "weekly_data", "search")}
    return {"writers." + name for name in normal}
