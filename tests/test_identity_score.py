"""Synthetic scorer controls. These fixtures are never product acceptance evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/verify-twinaatma/scripts/acceptance.py"
SPEC = importlib.util.spec_from_file_location("identity_quality_acceptance_controls", SCRIPT)
metric = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metric)

CASES = {
    "unknown": ("cold_init", "cold_self_get", "cold_session_start", "restart_self_get", "identity_preserved"),
    "canonical": ("marked_self_get", "marked_session_start", "marked_proposals", "aliases_self_get", "aliases_session_start",
                  "aliases_proposals", "duplicate_self_get", "duplicate_session_start", "duplicate_proposal", "identity_preserved"),
}
SECTIONS = ("heuristics", "values", "mental_models", "anti_goals", "active_bets", "drift_log")
CONTENTS = {
    "heuristics": "- Synthetic rule HX41. Compare one reversible option before choosing.\n- Synthetic rule HX42. Record evidence before generalizing.",
    "values": "1. Synthetic priority VX41. Keep explicit evidence above untested confidence.\n2. Synthetic priority VX42. Preserve time for careful review.",
    "mental_models": "- Synthetic model MX41. Separate observations from interpretations.\n- Synthetic model MX42. Consider the cost of reversing a decision.",
    "anti_goals": "- Synthetic limit AX41. Avoid irreversible changes based only on guesses.\n- Synthetic limit AX42. Avoid ranking another person's unstated values.",
    "active_bets": "- Synthetic bet BX41. Test a small local prototype this week.\n- Synthetic bet BX42. Reassess the prototype after measured feedback.",
    "drift_log": "| Topic | Shift Observed | Date Flagged | Evidence |\n|---|---|---|---|\n| Synthetic DX41 | Revised one prototype estimate | 2026-10-19 | fixture evidence DX42 |",
}
UNKNOWNS = {
    "heuristics": "Unknown. No owner-confirmed heuristics recorded yet.",
    "values": "Unknown. No owner-confirmed values or ranking recorded yet.",
    "mental_models": "Unknown. No owner-confirmed mental models recorded yet.",
    "anti_goals": "Unknown. No owner-confirmed anti-goals recorded yet.",
    "active_bets": "Unknown. No owner-confirmed strategic bets recorded yet.",
    "drift_log": "| Topic | Shift Observed | Date Flagged | Evidence |\n|---|---|---|---|\n| — | Vault initialized | 2026-10-19 | init |",
}


class ObservationFixtures:
    def setUp(self):
        base = ROOT / "work/gc-artifacts/.knowledgeos/identity-quality-score-20261019/unit-fixtures"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.fixture_index = 0
        self.current = {"knowledgeos/fake.py": "a" * 64, "AGENTS.md": "b" * 64}
        self.toolkit = dict(self.current, **{"scripts/operation.py": "c" * 64})
        self.producers = self.directory / "test-producers"
        self.producers.mkdir()
        for name in ("acceptance.py", "identity.py", "quality.py", "data_preservation.py"):
            (self.producers / name).write_text("# Synthetic scorer fixture only.\n", encoding="utf-8")
        for replacement in (patch.object(metric, "__file__", str(self.producers / "acceptance.py")),
                            patch.object(metric, "data_toolkit_hashes", return_value=self.toolkit),
                            patch.object(metric, "product_hashes", return_value=self.current)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def save(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def refresh(self, path, data):
        data["evidence_files"] = {member.name: metric.sha(member) for member in path.parent.iterdir()
                                  if member.is_file() and member.name != "report.json"}
        self.save(path, data)

    def base_report(self, directory, producer, filename, scope):
        directory.mkdir(exist_ok=True)
        sentinels = {str(ROOT / name): "d" * 64 for name in ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json")}
        data = {"producer": producer, "producer_sha256": metric.sha(self.producers / filename),
                "support_sha256": {"data_preservation.py": metric.sha(self.producers / "data_preservation.py")},
                "scope": scope, "platform": "synthetic scorer fixture", "python": sys.version, "revision": "e" * 40,
                "product_hashes": copy.deepcopy(self.toolkit), "product_hashes_after": copy.deepcopy(self.toolkit), "product_and_producer_unchanged": True,
                "verdict": "PASS", "error": None, "processes": [], "all_started_processes_stopped": True,
                "isolation": {"before": sentinels, "after": copy.deepcopy(sentinels), "selected_sentinels_unchanged": True}}
        self.command(directory, data, "revision", ["git", "rev-parse", "HEAD"], ROOT, state=directory / "gate-state", vault=None, stdout="e" * 40 + "\n")
        return data

    def command(self, directory, data, role, argv, cwd, *, state, vault, stdout="", import_path=None, quality=False):
        pid = 1000 + len(data["processes"])
        record = {"command": argv, "cwd": str(cwd), "shell": False, "vault": str(vault) if vault else None,
                  "state_dir": str(state), "pid": pid, "exit_code": 0, "stopped": True, "seconds": 0.01, "error": None}
        if import_path is not None:
            record["pythonpath" if quality else "import_path"] = str(import_path)
        self.save(directory / (role + ".command.json"), record)
        (directory / (role + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (directory / (role + ".stderr.txt")).write_text("", encoding="utf-8")
        data["processes"].append({"pid": pid, "role": role, "stopped": True, "exit_code": 0})

    def rpc(self, directory, data, role, fixture, calls, results, *, quality=False):
        vault = fixture / "vault"
        client = {"name": "verify-twinaatma" if quality else "verify-twinaatma-identity", "version": "1"}
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": client}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        requests += [{"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
                     for index, (name, arguments) in enumerate(calls, 2)]
        responses = [{"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "knowledgeos-memory"}}}]
        responses += [{"jsonrpc": "2.0", "id": index, "result": {"isError": result["is_error"],
            "content": [{"type": "text", "text": json.dumps(result["payload"], ensure_ascii=False)}]}} for index, result in enumerate(results, 2)]
        self.command(directory, data, role, [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", str(vault), "--framing", "ndjson"],
            directory if quality else fixture, state=fixture / "gate-state", vault=vault, quality=quality,
            import_path=vault if quality else fixture / "toolkit", stdout="".join(json.dumps(response, ensure_ascii=False) + "\n" for response in responses))
        self.save(directory / (role + ".requests.json"), requests)
        if not quality:
            self.save(directory / (role + ".results.json"), results)

    def identity_fixture(self, journey="unknown"):
        self.fixture_index += 1
        directory = self.directory / (journey + "-" + str(self.fixture_index))
        data = self.base_report(directory, "verify-twinaatma.identity-" + journey + "/v1", "identity.py", "source-only CLI initialization synthetic scorer control")
        data["cases"] = []
        preserved = []
        for kind in (("cold",) if journey == "unknown" else ("marked", "aliases", "duplicate")):
            fixture = directory / "fixtures" / kind
            vault = fixture / "vault"
            (vault / "People/Self-Proposals").mkdir(parents=True)
            self_path = vault / "People/Self.md"
            self_path.write_text("# Synthetic scorer Self.\n", encoding="utf-8")
            self_inventory = {"kind": "file", "links": 1, "size": self_path.stat().st_size, "sha256": metric.sha(self_path)}
            inventory = {"toolkit/" + name: {"kind": "file", "links": 1, "sha256": digest} for name, digest in self.toolkit.items()}
            inventory["vault/People/Self.md"] = self_inventory
            before = copy.deepcopy(inventory)
            self.save(directory / (kind + ".before.json"), before)
            copied = {name: {"kind": "file", "links": 1, "sha256": digest} for name, digest in self.toolkit.items()}
            for suffix in (".toolkit-before.json", ".toolkit-after.json"):
                self.save(directory / (kind + suffix), copied)
            initialized = {"ok": True, "owner": "Synthetic Unknown A47", "post_init": {"rebuild": {"ok": True}, "validate": {"ok": True}}}
            for operation, tail in (("init", ["init", str(vault), "--name", "Synthetic Unknown A47", "--non-interactive"]), ("doctor", ["doctor", "--vault", str(vault)])):
                self.command(directory, data, kind + "-" + operation, [sys.executable, "-B", "-P", "-m", "knowledgeos", *tail],
                    fixture, state=fixture / "gate-state", vault=vault, import_path=fixture / "toolkit", stdout=json.dumps(initialized) if operation == "init" else "ready\n")
            if kind == "cold":
                data["cases"].append({"id": "identity.unknown.cold_init", "verdict": "PASS", "expected": "Name only initialization succeeds",
                    "observed": {"initialized": initialized, "cli_exit_code": 0, "doctor_exit_code": 0, "only_supplied_identity_attribute": "name", "ready": True},
                    "evidence": ["cold-init.command.json", "cold-init.stdout.txt", "cold-init.stderr.txt", "cold-doctor.command.json", "cold-doctor.stdout.txt", "cold-doctor.stderr.txt", "cold.before.json"]})
            names = ("cold_self_get", "cold_session_start", "restart_self_get") if kind == "cold" else (kind + "_self_get", kind + "_session_start")
            for name in names:
                session = name.endswith("session_start")
                sections = {key: (("<!-- kos:section=" + key + " -->\n") if kind != "aliases" else "") + value
                            for key, value in (UNKNOWNS if kind == "cold" else CONTENTS).items()}
                payload = {"path": "People/Self.md", "sections": sections}
                arguments = {"task_hint": "What owner-confirmed preferences, ranked values, mental models, anti-goals and live bets do you know?",
                    "session_id": journey + "-" + kind + "-section-proof"} if session else {}
                result = {"payload": {"context": {"self": payload}, "session_id": arguments["session_id"]} if session else payload, "is_error": False}
                if kind == "duplicate":
                    result = {"payload": {"error": "duplicate kos:section=values"}, "is_error": True}
                role = journey + "-" + name
                self.rpc(directory, data, role, fixture, [("memory_session_start" if session else "memory_self_get", arguments)], [result])
                data["cases"].append({"id": "identity." + journey + "." + name, "verdict": "PASS", "expected": "Literal identity read",
                    "observed": {"payload": result["payload"] if kind == "duplicate" else payload, "is_error": result["is_error"],
                                 "public_result": result, "self_bytes_unchanged": True},
                    "evidence": [role + suffix for suffix in (".command.json", ".requests.json", ".stdout.txt", ".stderr.txt", ".results.json")]})
            proposals = {}
            if kind != "cold":
                name = kind + ("_proposal" if kind == "duplicate" else "_proposals")
                role = journey + "-" + name
                self.save(directory / (role + ".before.json"), before)
                calls, results, targets = [], [], []
                for key in (("values",) if kind == "duplicate" else SECTIONS):
                    patch_text = "- Synthetic addition PX41 for " + key + ". Compare retained evidence before revising this test preference."
                    calls.append(("memory_propose_self_update", {"summary": "Synthetic canonical target " + key, "section": key,
                        "proposed_markdown": patch_text, "rationale": "Synthetic source identity acceptance only.", "mode": "append"}))
                    if kind == "duplicate":
                        result = {"payload": {"error": "duplicate kos:section=values"}, "is_error": True}
                        targets.append({"payload": result["payload"], "proposal_evidence_unchanged": True})
                    else:
                        base = ("<!-- kos:section=" + key + " -->\n" if kind == "marked" else "") + CONTENTS[key]
                        digest = hashlib.sha256("\n".join(line.rstrip() for line in base.splitlines() if line.strip()).encode()).hexdigest()[:16]
                        raw = ("---\nproposal_section: " + key + "\nproposal_target: People/Self.md\nproposal_mode: append\nproposal_origin: memory_propose_self_update\nproposal_base_hash: "
                               + digest + "\nstatus: draft\n---\n```markdown\n" + patch_text + "\n```\n")
                        proposal = vault / "People/Self-Proposals" / (key + ".md")
                        proposal.write_text(raw, encoding="utf-8", newline="")
                        result = {"payload": {"ok": True, "policy": "proposal_only", "section": key, "base_digest": digest, "mutated_self": False,
                                             "proposal_path": "People/Self-Proposals/" + key + ".md"}, "is_error": False}
                        targets.append({"proposal_text": raw, "proposal_sha256": metric.sha(proposal), "result": result, "expected_base_digest": digest})
                        proposals[key + ".md"] = {"kind": "file", "links": 1, "size": proposal.stat().st_size, "sha256": metric.sha(proposal)}
                        inventory["vault/People/Self-Proposals/" + key + ".md"] = proposals[key + ".md"]
                    results.append(result)
                self.rpc(directory, data, role, fixture, calls, results)
                self.save(directory / (role + ".after.json"), inventory)
                self.save(directory / (role + ".proposal-observations.json"), targets)
                data["cases"].append({"id": "identity." + journey + "." + name, "verdict": "PASS", "expected": "Six exact proposals or duplicate refusal",
                    "observed": {"targets": targets, "self_bytes_unchanged": True}, "evidence": [role + suffix for suffix in (
                        ".command.json", ".requests.json", ".stdout.txt", ".stderr.txt", ".results.json", ".before.json", ".after.json", ".proposal-observations.json")]})
            self.save(directory / (kind + ".after.json"), inventory)
            preserved.append({"kind": kind, "self_before_sha256": self_inventory["sha256"], "self_after_sha256": self_inventory["sha256"],
                "toolkit_matches_product": True, "toolkit_unchanged": True, "all_other_note_bytes_unchanged": True,
                "prior_proposals_unchanged": True, "proposal_inventory": proposals})
        data["cases"].append({"id": "identity." + journey + ".identity_preserved", "verdict": "PASS", "expected": "All originals preserved",
                              "observed": {"fixtures": preserved}, "evidence": [kind + ".after.json" for kind in (("cold",) if journey == "unknown" else ("marked", "aliases", "duplicate"))]})
        data["expected_case_ids"] = ["identity." + journey + "." + name for name in CASES[journey]]
        path = directory / "report.json"
        self.refresh(path, data)
        return path, data


class IdentityScoreTests(ObservationFixtures, unittest.TestCase):
    def test_complete_identity_reports_award_only_two_existing_fixed_outcomes(self):
        reports = [metric.identity_report(self.identity_fixture(journey)[0], self.current) for journey in CASES]
        outcomes = {item["id"] for item in metric.read_json(metric.RUBRIC)["outcomes"] if metric.outcome(item, reports)["verdict"] == "PASS"}
        self.assertEqual(outcomes, {"IDENTITY.unknown_stays_unknown", "IDENTITY.canonical_sections"})
        self.assertEqual(metric.sha(metric.RUBRIC), "744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91")
        self.assertEqual(metric.ADAPTER_REQUIREMENTS["version"], "verify-twinaatma.adapters/v13")

    def test_partial_duplicate_unknown_or_manual_identity_cases_cannot_earn_credit(self):
        for change in (lambda d: d["cases"].pop(), lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])),
                       lambda d: d.update(producer="manual/identity"), lambda d: d["cases"][0].update(id="identity.owner_approved")):
            path, data = self.identity_fixture()
            change(data)
            self.save(path, data)
            with self.assertRaises(ValueError):
                metric.identity_report(path, self.current)

    def test_producer_product_sentinels_and_shutdown_are_fail_closed(self):
        for change in (lambda d: d.update(producer_sha256="0" * 64), lambda d: d["product_hashes_after"].update({"scripts/operation.py": "0" * 64}),
                       lambda d: d["isolation"].update(selected_sentinels_unchanged=False), lambda d: d["processes"][0].update(pid=True),
                       lambda d: d["processes"][0].update(stopped=False), lambda d: d.update(all_started_processes_stopped=False)):
            path, data = self.identity_fixture()
            change(data)
            self.save(path, data)
            with self.assertRaises(ValueError):
                metric.identity_report(path, self.current)

    def test_noop_wrong_vault_and_import_path_substitutions_are_rejected(self):
        for field, value in (("command", [sys.executable, "-c", "pass"]), ("vault", str(ROOT)), ("state_dir", str(ROOT)), ("import_path", str(ROOT))):
            path, data = self.identity_fixture()
            command = path.parent / "unknown-cold_self_get.command.json"
            record = metric.read_json(command)
            record[field] = value
            self.save(command, record)
            self.refresh(path, data)
            with self.assertRaisesRegex(ValueError, "command|argv|import path"):
                metric.identity_report(path, self.current)

    def test_missing_or_changed_protocol_trace_cannot_use_observed_flags(self):
        for mutation in ("missing", "raw", "parsed", "unknown"):
            path, data = self.identity_fixture()
            role = "unknown-cold_self_get"
            if mutation == "missing":
                (path.parent / (role + ".requests.json")).unlink()
            elif mutation == "raw":
                (path.parent / (role + ".stdout.txt")).write_text("{}\n", encoding="utf-8")
            elif mutation == "parsed":
                self.save(path.parent / (role + ".results.json"), [{"payload": {}, "is_error": False}])
            else:
                requests = metric.read_json(path.parent / (role + ".requests.json"))
                requests[-1]["params"]["name"] = "memory_accept_self_update"
                self.save(path.parent / (role + ".requests.json"), requests)
            self.refresh(path, data)
            with self.assertRaises(ValueError):
                metric.identity_report(path, self.current)

    def test_consistently_invented_unknown_value_is_still_rejected(self):
        path, data = self.identity_fixture()
        role = "unknown-cold_self_get"
        results = metric.read_json(path.parent / (role + ".results.json"))
        results[0]["payload"]["sections"]["values"] = "Invented personal confidence."
        self.save(path.parent / (role + ".results.json"), results)
        responses = [json.loads(line) for line in (path.parent / (role + ".stdout.txt")).read_text(encoding="utf-8").splitlines()]
        responses[-1]["result"]["content"][0]["text"] = json.dumps(results[0]["payload"])
        (path.parent / (role + ".stdout.txt")).write_text("".join(json.dumps(row) + "\n" for row in responses), encoding="utf-8")
        row = data["cases"][1]
        row["observed"].update(payload=results[0]["payload"], public_result=results[0])
        self.refresh(path, data)
        with self.assertRaisesRegex(ValueError, "Identity PASS"):
            metric.identity_report(path, self.current)

    def test_persisted_proposal_tamper_and_changed_self_are_rejected(self):
        for target in ("Self.md", "Self-Proposals/values.md"):
            path, data = self.identity_fixture("canonical")
            file = path.parent / "fixtures/marked/vault/People" / target
            file.write_text("Changed after observation\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Identity"):
                metric.identity_report(path, self.current)

    def test_reader_and_proposal_must_target_all_six_literal_sections(self):
        path, data = self.identity_fixture("canonical")
        observed = data["cases"][2]["observed"]["targets"]
        observed[0]["result"]["payload"]["section"] = "values"
        self.save(path, data)
        with self.assertRaises(ValueError):
            metric.identity_report(path, self.current)


if __name__ == "__main__":
    unittest.main()
