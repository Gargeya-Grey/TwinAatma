"""Observe one complete source identity-writer preservation unit in synthetic copies."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "knowledgeos/memory.py").is_file())
VERIFY = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(VERIFY))
from data_preservation import DataRun, inventory, sha
from identity import IdentityRun, fixture_identity
from maintenance import traced
from writer_census import read_census
from physical_observer import snapshot as physical_snapshot
from writer_contract import (PRODUCER, OUTCOME, SCOPE, SESSION, CAPTURE_NAME, HISTORY,
                             FIXTURE_NOTES, OUTCOME_ARGS, normal_calls, capture_call, proposal_call,
                             forget_call, alias_specs, directory_specs, public_operation, fault_operation,
                             legacy_specs, cli_arguments, SHELL_OBSERVER, SHELL_RUNNER, RUNTIME_OBSERVER)

SUPPORT = ("writer_census.py", "writer_contract.py", "physical_observer.py")
ROOT_SUPPORT = ("data_preservation.py", "identity.py", "maintenance.py")


def file_bytes_changed(before, after, key):
    return before.get(key, {}).get("sha256") != after.get(key, {}).get("sha256")


class WritersRun(IdentityRun):
    def __init__(self, output, freeze):
        super().__init__(output, "writers")
        self.env.pop("KNOWLEDGEOS_GATE_KEY", None)
        self.freeze = Path(freeze).absolute()
        self.freeze_hash = sha(self.freeze)
        frozen = json.loads(self.freeze.read_text(encoding="utf-8"))
        if frozen.get("product") != self.sources:
            raise ValueError("Complete current toolkit differs from the required frozen product")
        self.census = read_census(ROOT)
        self.save("writer-census.json", self.census)
        self.save("case-contract.json", {"producer": PRODUCER, "outcome": OUTCOME,
                  "hardlink_cases": [s["id"] for s in alias_specs()], "directory_cases": [s["id"] for s in directory_specs()],
                  "tools": self.census["memory_tools"], "frozen_before_any_product_invocation": True,
                  "freeze_path": str(self.freeze), "freeze_sha256": self.freeze_hash, "toolkit_hashes": self.sources})
        self.stage_hashes = {name: sha(HERE / name) for name in (*SUPPORT, "identity_writers.py")}
        self.root_support = {name: sha(VERIFY / name) for name in ROOT_SUPPORT}
        self.records = []
        self.checks = []

    def prepare_writer(self, label, *, legacy=False, history=False):
        scope = self.directory / "fixtures" / label
        toolkit = scope / ("vault" if legacy else "toolkit")
        vault = scope / "vault"
        toolkit.mkdir(parents=True)
        for source in self.inputs:
            destination = toolkit / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        (toolkit / "sitecustomize.py").write_text(RUNTIME_OBSERVER, encoding="utf-8")
        fixture = {"label": label, "kind": "legacy" if legacy else "standard", "scope": scope, "toolkit": toolkit, "vault": vault}
        self.fixtures.append(fixture)
        self.save(label + ".toolkit-initial.json", inventory(toolkit))
        if legacy:
            (vault / "People").mkdir(parents=True, exist_ok=True)
            (vault / "People/Self.md").write_bytes(fixture_identity("marked"))
            (vault / "People/Self-Proposals").mkdir()
            (vault / ".knowledgeos-vault.json").write_text(json.dumps({"vault": "twinaatma", "schema": "knowledgeos-v0.3", "vault_id": "ad4131" * 5 + "ab"}), encoding="utf-8")
        else:
            record, stdout, _ = self.cli(label + "-init", fixture, ["init", str(vault), "--name", "Synthetic writer IW41", "--non-interactive"])
            payload = json.loads(stdout) if record["exit_code"] == 0 else {}
            if record["exit_code"] != 0 or not (vault / "People/Self.md").is_file() or not payload.get("post_init"):
                raise RuntimeError("Fixture initialization failed: " + label)
        for relative, text in FIXTURE_NOTES.items():
            path = vault / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        if history:
            results = self.rpc(label + "-history-create", fixture, [("memory_propose_self_update", args) for args in HISTORY.values()])
            if any(row["is_error"] or not row["payload"].get("ok") for row in results):
                raise RuntimeError("Synthetic pending history could not be created")
            rejected = results[1]["payload"]["proposal_path"]
            result = self.rpc(label + "-history-reject", fixture, [("memory_reject_self_update", {"proposal_path": rejected, "reason": "Retain this synthetic rejected history."})])[0]
            if result["is_error"] or not result["payload"].get("ok"):
                raise RuntimeError("Synthetic rejected history could not be retained")
        fixture["initial_identity"] = inventory(vault / "People")
        self.save(label + ".identity-initial.json", fixture["initial_identity"])
        self.save(label + ".fixture-initial.json", inventory(scope))
        self.save(label + ".physical-initial.json", physical_snapshot(scope, label, alias_specs()))
        return fixture

    def snapshot(self, fixture, label, stage):
        value = inventory(fixture["scope"])
        self.save(label + "." + stage + ".json", value)
        self.save(label + ".physical-" + stage + ".json", physical_snapshot(fixture["scope"], label, alias_specs()))
        return value

    def record_case(self, name, fixture, before, after, *, kind, roles, calls=None, expected=None, detail=None):
        self_key = "vault/People/Self.md"
        before_self = before.get(self_key)
        after_self = after.get(self_key)
        allowed_rejection = {"vault/" + calls[0][1]["proposal_path"]} if kind == "reject" else set()
        if name == "script-propose_self_update-3":
            arguments = detail["arguments"]
            allowed_rejection = {"vault/" + arguments[arguments.index("reject") + 1]}
        protected = {p: row for p, row in before.items() if p.startswith("vault/People/") and row.get("kind") == "file" and p not in allowed_rejection}
        physical_before = json.loads((self.directory / (name + ".physical-before.json")).read_text(encoding="utf-8"))
        physical_after = json.loads((self.directory / (name + ".physical-after.json")).read_text(encoding="utf-8"))
        expected_self = dict(before_self) if before_self else None
        detached = False
        if name in {"hard-index-manifest", "symlink-index-manifest"}:
            original = physical_before["self"]
            left, right = physical_before["alias"], physical_after["alias"]
            linked = left.get("effective") if name.startswith("symlink-") else left
            if right and right.get("kind") == "file" and right.get("links") == 1 and linked and all(linked.get(key) == original[key] for key in ("device", "inode", "size", "links", "sha256")) and (right["device"], right["inode"]) != (original["device"], original["inode"]):
                expected_self["links"] -= int(name.startswith("hard-"))
                detached = True
        expected_physical = dict(physical_before["self"])
        expected_physical["links"] = expected_self["links"]
        physical_same = expected_physical == physical_after["self"]
        same = all(after.get(p) == (expected_self if p == self_key else row) for p, row in protected.items())
        source_prefix = "vault/" if fixture["toolkit"] == fixture["vault"] else "toolkit/"
        source_same = all(after.get(source_prefix + p, {}).get("sha256") == digest for p, digest in self.sources.items())
        row = {"id": "writers." + name, "fixture": fixture["label"], "kind": kind, "roles": roles,
               "before": name + ".before.json", "after": name + ".after.json", "calls": calls,
               "expected": expected or "Public callers preserve the exact identity and existing proposal history.",
               "observed": {"self_before": before_self, "self_after": after_self,
                            "existing_identity_files_unchanged": same, "complete_toolkit_source_unchanged": source_same,
                            "original_physical_self_preserved": physical_same, "safe_manifest_alias_detached": detached},
               "detail": detail or {}}
        row["verdict"] = "PASS" if same and expected_self == after_self and physical_same and source_same else "FAIL"
        self.checks.append(row)
        print(row["verdict"] + " " + row["id"], flush=True)

    def rpc_case(self, name, fixture, calls, *, kind="rpc", detail=None):
        before = self.snapshot(fixture, name, "before")
        results = self.rpc(name, fixture, calls)
        after = self.snapshot(fixture, name, "after")
        self.record_case(name, fixture, before, after, kind=kind, roles=[name], calls=calls, detail=detail)
        return results

    def cli_case(self, name, fixture, arguments, *, kind="cli", detail=None, fault=None):
        before = self.snapshot(fixture, name, "before")
        if fault:
            self.activate(fixture)
            operation = public_operation(arguments)
            command = [sys.executable, "-B", "-P", "-c", fault_operation(operation, fault)]
            record, stdout, stderr = self.command(name, command, fixture["scope"], fixture["vault"], timeout=90)
            record["import_path"] = str(fixture["toolkit"])
            self.save(name + ".command.json", record)
        elif name == "cli-hook-start":
            self.activate(fixture)
            record, stdout, stderr = self.command(name, [sys.executable, "-B", "-P", "-c", traced(public_operation(arguments))], fixture["scope"], fixture["vault"], timeout=100)
            record["import_path"] = str(fixture["toolkit"])
            self.save(name + ".command.json", record)
        else:
            record, stdout, stderr = self.cli(name, fixture, arguments)
        after = self.snapshot(fixture, name, "after")
        self.record_case(name, fixture, before, after, kind=kind, roles=[name], detail={"arguments": arguments, "fault_target": fault, **(detail or {})})
        return record, stdout, stderr

    def script_case(self, name, fixture, relative, arguments=(), *, shell=False):
        before = self.snapshot(fixture, name, "before")
        self.activate(fixture)
        operation = ("import runpy, sys\nsys.argv = " + repr([relative, *map(str, arguments)]) +
                     "\nrunpy.run_path(" + repr(str(fixture["toolkit"] / relative)) + ", run_name='__main__')")
        if shell:
            observer = fixture["scope"] / "shell-observer.sh"
            observer.write_text(SHELL_OBSERVER, encoding="utf-8")
            self.env.update(BASH_ENV=str(observer), WRITER_PYTHON=sys.executable, WRITER_SCRIPT_RUNNER=SHELL_RUNNER)
            command = ["bash", str(fixture["toolkit"] / relative), *map(str, arguments)]
        else:
            command = [sys.executable, "-B", "-P", "-c", traced(operation)]
        try:
            record, stdout, stderr = self.command(name, command, fixture["vault"], fixture["vault"], timeout=100)
        finally:
            if shell:
                for key in ("BASH_ENV", "WRITER_PYTHON", "WRITER_SCRIPT_RUNNER"):
                    self.env.pop(key, None)
        record["import_path"] = str(fixture["toolkit"])
        self.save(name + ".command.json", record)
        after = self.snapshot(fixture, name, "after")
        detail = {"script": relative, "arguments": list(map(str, arguments)), "shell": shell}
        self.record_case(name, fixture, before, after, kind="script", roles=[name], detail=detail)
        return record, stdout, stderr

    def normal(self):
        fixture = self.prepare_writer("normal", history=True)
        results = self.rpc_case("normal-tools", fixture, normal_calls(), kind="normal-tools")
        proposal = results[15]["payload"].get("proposal_path", "missing")
        self.rpc_case("normal-reject", fixture, [("memory_reject_self_update", {"proposal_path": proposal, "reason": "Synthetic writer proof declines this draft."})], kind="reject", detail={"created_by": "normal-tools", "result_index": 15})
        self.cli_case("cli-capture", fixture, ["memory", "memory_capture", "--vault", str(fixture["vault"]), "--args", json.dumps({"title": "CLI writer IW41", "content": "A synthetic CLI capture preserves identity."})])
        self.cli_case("cli-breathe", fixture, ["breathe", "--vault", str(fixture["vault"]), "--task-hint", "writer preservation"])
        self.cli_case("cli-self-summary", fixture, cli_arguments("cli-self-summary", fixture))
        self.cli_case("cli-self-pending", fixture, cli_arguments("cli-self-pending", fixture))
        self.cli_case("cli-hook-end", fixture, ["hook", "twin_session_end", "--vault", str(fixture["vault"])])
        self.cli_case("cli-hook-start", fixture, cli_arguments("cli-hook-start", fixture), kind="hook-cli")
        self.cli_case("init-refresh", fixture, ["init", str(fixture["vault"]), "--name", "Another synthetic supplied name", "--force", "--non-interactive"], kind="init-refresh")
        for host in ("cursor", "vscode", "codex"):
            self.cli_case("setup-" + host, fixture, ["setup-host", "--host", host, "--vault", str(fixture["vault"]), "--write"], kind="setup")
        self.cli_case("setup-out-existing-self", fixture, ["setup-host", "--host", "cursor", "--vault", str(fixture["vault"]), "--out", str(fixture["vault"] / "People/Self.md")], kind="refuse-cli")
        self.cli_case("setup-out-new", fixture, ["setup-host", "--host", "cursor", "--vault", str(fixture["vault"]), "--out", str(fixture["scope"] / "new-host.json")], kind="setup")
        first = capture_call()
        self.rpc_case("capture-first", fixture, [first], kind="capture-first")
        self.rpc_case("capture-collision", fixture, [(first[0], dict(first[1], content="Different synthetic content for the same reviewed request."))], kind="refuse-rpc")
        self.rpc_case("outcome-protected-self", fixture, [("memory_record_outcome", dict(OUTCOME_ARGS, path="People/Self.md", expected_sha256=sha(fixture["vault"] / "People/Self.md")))], kind="refuse-rpc")
        for tool in ("memory_forget", "memory_supersede"):
            args = {"path_or_id": "People/Self.md", "expected_sha256": sha(fixture["vault"] / "People/Self.md")}
            if tool.endswith("supersede"):
                args.update(replacement_path_or_id="Concepts/New.md", replacement_sha256=sha(fixture["vault"] / "Concepts/New.md"))
            self.rpc_case(tool + "-self", fixture, [(tool, args)], kind="policy-self")

    def aliases(self):
        for spec in alias_specs():
            fixture = self.prepare_writer("hard-" + spec["id"])
            target = fixture["scope"] / spec["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rename(target.with_name(target.name + ".retained-before-alias"))
            os.link(fixture["vault"] / "People/Self.md", target)
            self.rpc_case("hard-" + spec["id"], fixture, [spec["call"]], kind="file-alias", detail={"path": spec["path"], "alias": "hardlink"})
        for host, relative in (("cursor", ".cursor/mcp.json"), ("vscode", ".vscode/mcp.json"), ("codex", ".codex/config.toml")):
            fixture = self.prepare_writer("hard-setup-" + host)
            target = fixture["vault"] / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rename(target.with_name(target.name + ".retained-before-alias"))
            os.link(fixture["vault"] / "People/Self.md", target)
            self.cli_case("hard-setup-" + host, fixture, ["setup-host", "--host", host, "--vault", str(fixture["vault"]), "--write"], kind="file-alias-cli", detail={"path": "vault/" + relative, "alias": "hardlink"})
        for spec in directory_specs():
            fixture = self.prepare_writer("directory-" + spec["id"])
            target = fixture["scope"] / spec["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            outside = fixture["scope"] / "outside"
            outside.mkdir()
            (outside / "Self-protected.md").write_bytes((fixture["vault"] / "People/Self.md").read_bytes())
            if target.exists():
                target.rename(target.with_name(target.name + ".retained-before-alias"))
            if os.name == "nt":
                record, _, _ = self.command("directory-" + spec["id"] + "-junction", ["cmd", "/c", "mklink", "/J", str(target), str(outside)], fixture["scope"], timeout=30)
                if record["exit_code"]:
                    raise RuntimeError("Native directory junction setup failed")
            else:
                target.symlink_to(outside, target_is_directory=True)
            self.rpc_case("directory-" + spec["id"], fixture, spec["calls"], kind="directory-alias", detail={"path": spec["path"], "alias": "junction" if os.name == "nt" else "symlink"})
        if os.name != "nt":
            for spec in alias_specs():
                name = "symlink-" + spec["id"]
                fixture = self.prepare_writer(name)
                target = fixture["scope"] / spec["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target.rename(target.with_name(target.name + ".retained-before-alias"))
                target.symlink_to(fixture["vault"] / "People/Self.md")
                self.rpc_case(name, fixture, [spec["call"]], kind="file-alias", detail={"path": spec["path"], "alias": "symlink"})
            for host, relative in (("cursor", ".cursor/mcp.json"), ("vscode", ".vscode/mcp.json"), ("codex", ".codex/config.toml")):
                name = "symlink-setup-" + host
                fixture = self.prepare_writer(name)
                target = fixture["vault"] / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target.rename(target.with_name(target.name + ".retained-before-alias"))
                target.symlink_to(fixture["vault"] / "People/Self.md")
                self.cli_case(name, fixture, cli_arguments(name, fixture), kind="file-alias-cli", detail={"path": "vault/" + relative, "alias": "symlink"})

    def legacy(self):
        fixture = self.prepare_writer("legacy", legacy=True)
        self.cli_case("legacy-outcome", fixture, cli_arguments("legacy-outcome", fixture))
        for name, relative, args in legacy_specs(fixture):
            record, stdout, stderr = self.script_case(name, fixture, relative, args)
            if name == "script-propose_self_update-0":
                proposal = json.loads(stdout)["proposal_path"] if record["exit_code"] == 0 else "missing"
        self.script_case("script-propose_self_update-3", fixture, "scripts/propose_self_update.py", ["--vault", str(fixture["vault"]), "reject", proposal, "--reason", "Synthetic source wrapper rejection."])
        if os.name != "nt":
            for relative, arguments in (("scripts/rebuild_index.sh", []), ("scripts/capture.sh", ["Concepts/Source.md"]),
                                        ("scripts/weekly_data.sh", []), ("scripts/search.sh", ["prototype"])):
                self.script_case("shell-" + Path(relative).stem, fixture, relative, arguments, shell=True)

    def faults(self):
        for name, tool, args, target in (
            ("capture-fault", *capture_call(), CAPTURE_NAME),
            ("outcome-fault", "memory_record_outcome", OUTCOME_ARGS, "Decisions/Review.md"),
            ("policy-fault", *forget_call(), ".knowledgeos/remembering-policy.json"),
        ):
            fixture = self.prepare_writer(name)
            arguments = ["memory", tool, "--vault", str(fixture["vault"]), "--args", json.dumps(args)]
            self.cli_case(name, fixture, arguments, kind="fault", fault=target)
            self.cli_case(name + "-retry", fixture, arguments, kind="retry")
        fixture = self.prepare_writer("setup-fault")
        arguments = ["setup-host", "--host", "cursor", "--vault", str(fixture["vault"]), "--write"]
        self.cli_case("setup-fault", fixture, arguments, kind="fault", fault=".cursor/mcp.json")
        self.cli_case("setup-fault-retry", fixture, arguments, kind="retry")

    def finish(self, error):
        fixture_rows = []
        for fixture in self.fixtures:
            label = fixture["label"]
            self.save(label + ".fixture-final.json", inventory(fixture["scope"]))
            self.save(label + ".identity-final.json", inventory(fixture["vault"] / "People") if (fixture["vault"] / "People").is_dir() else {})
            self.save(label + ".toolkit-final.json", inventory(fixture["toolkit"]))
            self.save(label + ".physical-final.json", physical_snapshot(fixture["scope"], label, alias_specs()))
            fixture_rows.append({key: str(fixture[key]) for key in ("label", "kind", "scope", "toolkit", "vault")})
        current = {p.relative_to(ROOT).as_posix(): sha(p) for p in self.inputs}
        after = self.sentinels()
        stable = current == self.sources and all(sha(HERE / name) == value for name, value in self.stage_hashes.items())
        stable = stable and all(sha(VERIFY / name) == value for name, value in self.root_support.items()) and sha(self.freeze) == self.freeze_hash
        stopped = bool(self.processes) and all(row["stopped"] and isinstance(row.get("exit_code"), int) for row in self.processes)
        report = {"producer": PRODUCER, "producer_sha256": sha(__file__), "support_sha256": {k: v for k, v in self.stage_hashes.items() if k != "identity_writers.py"},
                  "root_support_sha256": self.root_support, "scope": SCOPE, "outcome": OUTCOME,
                  "platform": platform.platform(), "os_name": os.name, "python": sys.version, "interpreter": sys.executable,
                  "producer_pid": os.getpid(),
                  "product_hashes": self.sources, "product_hashes_after": current, "product_and_producer_unchanged": stable,
                  "freeze_path": str(self.freeze), "freeze_sha256": self.freeze_hash, "source_census": "writer-census.json",
                  "fixtures": fixture_rows, "cases": self.checks, "processes": self.processes, "all_started_processes_stopped": stopped,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": self.before == after},
                  "error": error, "verdict": "FAIL" if error or not stable or not stopped or self.before != after or any(row["verdict"] != "PASS" for row in self.checks) else "PASS",
                  "limits": ["Only IDENTITY.all_writers_preserve is eligible after independent complete source evidence grading.",
                             "No owner approval, acceptance, installed distribution, host-answer or privacy-policy credit.",
                             "Windows file-symlink privilege is unavailable. Native Linux source observation supplies symlink and shell-wrapper coverage.",
                             "Before/after observation cannot detect a malicious trusted producer restoring bytes between observations."]}
        report["evidence_files"] = {p.name: sha(p) for p in self.directory.iterdir() if p.is_file()}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "producer_verdict": report["verdict"], "observed_cases": len(self.checks), "final_acceptance": "pending independent complete-input grading"}))
        return 1 if report["verdict"] == "FAIL" else 0

    def run(self):
        error = None
        try:
            self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            self.normal()
            self.aliases()
            self.legacy()
            self.faults()
        except BaseException as caught:
            error = {"type": type(caught).__name__, "message": str(caught)}
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--freeze", required=True)
    args = parser.parse_args()
    return WritersRun(args.output, args.freeze).run()


if __name__ == "__main__":
    raise SystemExit(main())
