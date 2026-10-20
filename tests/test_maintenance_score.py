"""Synthetic scorer controls, never acceptance evidence for the product."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/verify-twinaatma/scripts/acceptance.py"
SPEC = importlib.util.spec_from_file_location("maintenance_acceptance_controls", SCRIPT)
metric = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metric)

CASES = {
    "maintenance": ("ids_dry_run", "ids_write", "ids_schema", "ids_replace_fault", "ids_write_fault",
                    "ids_hardlink_self", "ids_hardlink_proposal", "ids_linked_directory", "links_write",
                    "links_replace_fault", "maps_write", "maps_edited", "maps_replace_fault"),
    "hooks": ("existing", "custom", "external", "linked_directory", "linked_file", "hardlinked_file", "write_fault", "chmod_fault"),
    "validation": ("good", "missing", "status", "date", "tags", "schema", "id", "duplicate", "broken", "ambiguous"),
}
PRODUCERS = {"maintenance": "verify-twinaatma.maintenance/v1", "hooks": "verify-twinaatma.hooks-preservation/v1",
             "validation": "verify-twinaatma.validation/v1"}


class MaintenanceScoreTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "work/gc-artifacts/.knowledgeos/maintenance-score-20261019/unit-fixtures"
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.current = {"knowledgeos/fake.py": "a" * 64, "AGENTS.md": "b" * 64}
        self.toolkit = dict(self.current, **{"scripts/update_mocs.py": "c" * 64})
        self.producers = self.directory / "test-producers"
        self.producers.mkdir()
        for name in ("acceptance.py", "maintenance.py", "data_preservation.py"):
            (self.producers / name).write_text("# Synthetic adapter unit fixture only.\n", encoding="utf-8")
        for replacement in (patch.object(metric, "__file__", str(self.producers / "acceptance.py")),
                            patch.object(metric, "data_toolkit_hashes", return_value=self.toolkit),
                            patch.object(metric, "product_hashes", return_value=self.current)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def save(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def report(self, journey="maintenance"):
        directory = self.directory / journey
        directory.mkdir(exist_ok=True)
        producer = PRODUCERS[journey]
        data = {"producer": producer, "producer_sha256": metric.sha(self.producers / "maintenance.py"),
                "support_sha256": {"data_preservation.py": metric.sha(self.producers / "data_preservation.py")},
                "scope": "source-only synthetic adapter unit fixture", "platform": "Linux-synthetic", "python": sys.version,
                "product_hashes": self.toolkit, "product_hashes_after": self.toolkit,
                "product_and_producer_unchanged": True, "cases": [], "verdict": "PASS", "error": None,
                "processes": [], "all_started_processes_stopped": True, "nested_processes": [],
                "nested_expectations": [], "nested_process_tracking_complete": True}
        sentinels = {str(ROOT / name): "d" * 64 for name in
                     ("People/Self.md", "knowledge_index.db", ".knowledgeos/autopilot.json")}
        data["isolation"] = {"before": sentinels, "after": copy.deepcopy(sentinels), "selected_sentinels_unchanged": True}

        def command(role, vault, argv, children=(), expected_scripts=None, exit_code=0):
            pid = 1000 + len(data["processes"])
            record = {"pid": pid, "exit_code": exit_code, "stopped": True, "shell": False, "command": argv,
                      "cwd": str(vault), "vault": str(vault), "state_dir": str(directory / "gate-state"),
                      "seconds": 0.01, "error": None}
            self.save(directory / (role + ".command.json"), record)
            data["processes"].append({"pid": pid, "role": role, "stopped": True, "exit_code": exit_code})
            (directory / (role + ".stdout.txt")).write_text("Synthetic unit fixture only.\n", encoding="utf-8")
            trace = {"parent_pid": pid, "children": [dict(child, pid=10000 + pid * 10 + index, stopped=True)
                                                       for index, child in enumerate(children)]}
            stderr = ""
            if len(argv) == 4 and argv[1:3] == ["-B", "-c"]:
                stderr = "MAINTENANCE_CHILDREN=" + json.dumps(trace) + "\n"
                self.save(directory / (role + ".nested.json"), {"trace": trace, "complete": True})
            (directory / (role + ".stderr.txt")).write_text(stderr, encoding="utf-8")
            for index, child in enumerate(trace["children"]):
                data["nested_processes"].append(dict(child, id=role + "-nested-" + str(index), parent_role=role,
                    parent_pid=pid, evidence=role + ".stderr.txt", evidence_sha256=metric.sha(directory / (role + ".stderr.txt"))))
            if expected_scripts is not None:
                data["nested_expectations"].append({"parent_role": role, "expected_scripts": expected_scripts,
                                                     "observed_scripts": expected_scripts, "complete": True})

        copied = {"vault/" + name: {"kind": "file", "links": 1, "sha256": digest}
                  for name, digest in self.toolkit.items()}
        for index, name in enumerate(CASES[journey]):
            label = journey + "-" + name
            vault = directory / ("fixtures/m" + str(index) + "/vault")
            vault.mkdir(parents=True, exist_ok=True)
            references = [label + ".before.json", label + ".after.json"]
            self.save(directory / references[0], copied)
            self.save(directory / references[1], copied)
            steps = []
            if journey == "maintenance":
                if name.startswith("ids_"):
                    args = ["ids", "assign", "--vault", str(vault)] + ([] if name == "ids_dry_run" else ["--write"])
                    steps = [(label, "from knowledgeos.__main__ import main\nmain(" + repr(args) + ")", [], None)]
                elif name.startswith("links_"):
                    steps = [(label, "import runpy\nrunpy.run_path('scripts/refactor_links.py', run_name='__main__')", [], None)]
                else:
                    steps = [(label + "-index", "from knowledgeos.indexer import rebuild_index\nrebuild_index('.')", [], None)]
                    if name == "maps_replace_fault":
                        steps += [(label + "-initial", "import runpy\nrunpy.run_path('scripts/update_mocs.py', run_name='__main__')", [], [])]
                        steps += [(label + "-changed-index", "from knowledgeos.indexer import rebuild_index\nrebuild_index('.')", [], None)]
                    steps += [(label, "import runpy\nrunpy.run_path('scripts/update_mocs.py', run_name='__main__')", [], [])]
                    if name == "maps_write":
                        steps += [(label + "-repeat", "import runpy\nrunpy.run_path('scripts/update_mocs.py', run_name='__main__')", [], [])]
                    rebuilt = []
                    for role, code, children, expected in steps:
                        if expected is not None:
                            expected = ["experiment_dashboard.py"] if name == "maps_edited" else ["experiment_dashboard.py", "outcomes_dashboard.py"]
                            children = [{"argv": [sys.executable, str(vault / "scripts" / script)], "exit_code": 1 if name == "maps_edited" else 0}
                                        for script in expected]
                        rebuilt.append((role, code, children, expected))
                    steps = rebuilt
            elif journey == "hooks":
                command(label + "-git-init", vault, ["git", "init", "--quiet", str(vault)])
                if name in ("custom", "external", "linked_directory"):
                    location = ".custom-hooks" if name == "custom" else str(vault.parent / "outside") if name == "external" else ".linked-hooks"
                    command(label + "-git-config", vault, ["git", "-C", str(vault), "config", "core.hooksPath", location])
                git = [{"argv": ["git", "-C", str(vault), "rev-parse", "--path-format=absolute", "--git-path", "hooks"], "exit_code": 0}]
                code = "import runpy\nrunpy.run_path('scripts/setup_git_hooks.py', run_name='__main__')"
                steps = [(label, code, git, None)] + ([(label + "-repeat", code, git, None)] if name == "custom" else [])
            else:
                args = ["validate", "--vault", str(vault)]
                steps = [(label + "-cli", "from knowledgeos.__main__ import main\nmain(" + repr(args) + ")", [], None),
                         (label + "-script", "import runpy, sys\nsys.argv = ['validate_schema.py', '--vault', " + repr(str(vault)) + "]\nrunpy.run_path('scripts/validate_schema.py', run_name='__main__')", [], None)]
            for role, code, children, expected in steps:
                command(role, vault, [sys.executable, "-B", "-c", code], children, expected)
                references += [role + suffix for suffix in (".command.json", ".stdout.txt", ".stderr.txt")]
            if journey == "hooks" and name == "custom":
                command(label + "-run", vault, ["git", "-C", str(vault), "hook", "run", "pre-commit"])
                references += [label + "-run" + suffix for suffix in (".command.json", ".stdout.txt", ".stderr.txt")]
            data["cases"].append({"id": "data." + journey + "." + name, "verdict": "PASS", "expected": "Synthetic literal expectation",
                                  "observed": {"literal": "Synthetic unit fixture only"}, "evidence": references})
        path = directory / "report.json"
        self.refresh(path, data)
        return path, data

    def refresh(self, path, data):
        data["evidence_files"] = {member.name: metric.sha(member) for member in path.parent.iterdir()
                                  if member.is_file() and member.name != path.name}
        self.save(path, data)

    def parse(self, path):
        return metric.data_report(path, self.current)

    def test_fixed_registry_adds_only_the_three_existing_source_outcomes(self):
        self.assertEqual(metric.ADAPTER_REQUIREMENTS["version"], "verify-twinaatma.adapters/v12")
        self.assertEqual({spec["outcome"] for spec in metric.MAINTENANCE_PRODUCERS.values()},
                         {"DATA.safe_maintenance", "DATA.preserve_hooks", "DATA.honest_validation"})
        for journey, producer in PRODUCERS.items():
            self.assertEqual(metric.MAINTENANCE_PRODUCERS[producer]["cases"],
                             {"data." + journey + "." + name for name in CASES[journey]})
        self.assertEqual(metric.sha(metric.RUBRIC), "744e4913702f6fdf344f233491f019737aa1a2d5adf65edf7ab1c48fce98aa91")
        self.assertEqual(len(metric.read_json(metric.RUBRIC)["outcomes"]), 54)

    def test_complete_reports_award_only_the_three_fixed_maintenance_outcomes(self):
        reports = [self.parse(self.report(journey)[0]) for journey in ("maintenance", "hooks", "validation")]
        rubric = metric.read_json(metric.RUBRIC)
        self.assertEqual({item["id"] for item in rubric["outcomes"] if metric.outcome(item, reports)["verdict"] == "PASS"},
                         {"DATA.safe_maintenance", "DATA.preserve_hooks", "DATA.honest_validation"})

    def test_nested_shutdown_claims_need_the_complete_retained_trace(self):
        for field, value in (("nested_processes", []), ("nested_expectations", []),
                             ("nested_process_tracking_complete", False)):
            with self.subTest(field=field):
                path, data = self.report()
                data[field] = value
                self.save(path, data)
                with self.assertRaisesRegex(ValueError, "nested|Nested"):
                    self.parse(path)

    def test_missing_or_nonpassing_cases_earn_no_partial_credit(self):
        for journey in ("maintenance", "hooks", "validation"):
            with self.subTest(journey=journey):
                path, data = self.report(journey)
                missing = data["cases"].pop()
                self.save(path, data)
                aggregate = metric.MAINTENANCE_PRODUCERS[PRODUCERS[journey]]["aggregate"]
                self.assertEqual(self.parse(path)["checks"][aggregate]["verdict"], "NOT CHECKED")
                data["cases"].append(missing)
                for verdict in ("FAIL", "BLOCKED", "NOT CHECKED"):
                    data["cases"][0]["verdict"] = verdict
                    self.save(path, data)
                    self.assertEqual(self.parse(path)["checks"][aggregate]["verdict"], verdict)

    def test_nested_report_rows_bind_parent_pid_role_evidence_hash_and_typed_exit(self):
        for field, value in (("stopped", False), ("stopped", 1), ("exit_code", None), ("exit_code", False),
                             ("pid", True), ("parent_pid", 999), ("parent_role", "unknown"),
                             ("evidence", "unknown.stderr.txt"), ("evidence_sha256", "0" * 64),
                             ("argv", [sys.executable, "scripts/not_the_dashboard.py"])):
            with self.subTest(field=field, value=value):
                path, data = self.report()
                data["nested_processes"][0][field] = value
                self.save(path, data)
                with self.assertRaisesRegex(ValueError, "nested|Nested"):
                    self.parse(path)

    def mutate_trace(self, path, data, role, change):
        retained_path = path.parent / (role + ".nested.json")
        retained = metric.read_json(retained_path)
        change(retained["trace"])
        self.save(retained_path, retained)
        stderr_path = path.parent / (role + ".stderr.txt")
        stderr_path.write_text("MAINTENANCE_CHILDREN=" + json.dumps(retained["trace"]) + "\n", encoding="utf-8")
        for row in data["nested_processes"]:
            if row["parent_role"] == role:
                row["evidence_sha256"] = metric.sha(stderr_path)
        self.refresh(path, data)

    def test_rehashed_nested_trace_still_requires_known_child_argv_and_fixture(self):
        for argv in ([sys.executable, "scripts/experiment_dashboard.py"],
                     [sys.executable, str(ROOT / "scripts/experiment_dashboard.py")],
                     ["other-python", "scripts/experiment_dashboard.py"], ["git", "status"]):
            with self.subTest(argv=argv):
                path, data = self.report()
                role = "maintenance-maps_write"
                self.mutate_trace(path, data, role, lambda trace: trace["children"][0].update(argv=argv))
                with self.assertRaisesRegex(ValueError, "nested|Nested"):
                    self.parse(path)

    def test_missing_duplicate_malformed_and_partial_parent_traces_are_rejected(self):
        for replacement in ("", "MAINTENANCE_CHILDREN={}\n", "MAINTENANCE_CHILDREN=invalid-json\n", "duplicate"):
            with self.subTest(replacement=replacement):
                path, data = self.report()
                target = path.parent / "maintenance-maps_write.stderr.txt"
                target.write_text(target.read_text(encoding="utf-8") * 2 if replacement == "duplicate" else replacement, encoding="utf-8")
                self.refresh(path, data)
                with self.assertRaisesRegex(ValueError, "nested|Nested"):
                    self.parse(path)
        for change in (lambda trace: trace.update(parent_pid=True), lambda trace: trace.update(parent_pid=999),
                       lambda trace: trace["children"].pop(), lambda trace: trace["children"][0].update(stopped=False),
                       lambda trace: trace["children"][0].update(exit_code=False)):
            path, data = self.report()
            self.mutate_trace(path, data, "maintenance-maps_write", change)
            with self.assertRaisesRegex(ValueError, "nested|Nested"):
                self.parse(path)

    def test_missing_mutated_or_untracked_nested_files_are_rejected(self):
        path, data = self.report()
        target = path.parent / "maintenance-maps_write.nested.json"
        target.unlink()
        self.refresh(path, data)
        with self.assertRaisesRegex(ValueError, "nested|Nested"):
            self.parse(path)
        path, data = self.report()
        retained = metric.read_json(target)
        retained["complete"] = 1
        self.save(target, retained)
        self.refresh(path, data)
        with self.assertRaisesRegex(ValueError, "nested|Nested"):
            self.parse(path)
        path, data = self.report()
        self.save(path.parent / "untracked.nested.json", {"trace": {}, "complete": True})
        self.refresh(path, data)
        with self.assertRaisesRegex(ValueError, "nested|Nested"):
            self.parse(path)

    def test_known_public_commands_cannot_be_replaced_with_noops_or_other_vaults(self):
        for command in ([sys.executable, "-B", "-c", "print('pass')"],
                        [sys.executable, "-B", "-c", "from knowledgeos.__main__ import main\nmain(['ids','assign','--vault', 'other-vault'])"],
                        [sys.executable, "-B", "-c", "from knowledgeos.__main__ import main\nmain(['validate', '--vault', '.'])"]):
            with self.subTest(command=command):
                path, data = self.report()
                target = path.parent / "maintenance-ids_write.command.json"
                record = metric.read_json(target)
                record["command"] = command
                self.save(target, record)
                self.refresh(path, data)
                with self.assertRaisesRegex(ValueError, "Maintenance command"):
                    self.parse(path)

    def test_windows_inapplicable_chmod_never_awards_hook_acceptance(self):
        path, data = self.report("hooks")
        data["platform"] = "Windows-synthetic"
        case = next(row for row in data["cases"] if row["id"] == "data.hooks.chmod_fault")
        case.update(verdict="NOT APPLICABLE", evidence=[])
        linked = next(row for row in data["cases"] if row["id"] == "data.hooks.linked_directory")
        linked.update(verdict="NOT CHECKED", evidence=[])
        self.save(path, data)
        self.assertEqual(self.parse(path)["checks"]["data.hooks.complete"]["verdict"], "NOT CHECKED")
        data["platform"] = "Linux-synthetic"
        self.save(path, data)
        with self.assertRaisesRegex(ValueError, "verdict"):
            self.parse(path)

    def test_duplicate_nested_ids_and_invented_script_expectations_are_rejected(self):
        for change in (lambda data: data["nested_processes"][1].update(id=data["nested_processes"][0]["id"]),
                       lambda data: data["nested_expectations"][0].update(expected_scripts=["different.py"]),
                       lambda data: data["nested_expectations"][0].update(complete=1),
                       lambda data: data["nested_expectations"].append(copy.deepcopy(data["nested_expectations"][0]))):
            path, data = self.report()
            change(data)
            self.save(path, data)
            with self.assertRaisesRegex(ValueError, "nested|Nested"):
                self.parse(path)

    def test_complete_case_needs_the_actual_public_command_and_owned_launch(self):
        for referenced in (False, True):
            path, data = self.report()
            role = "maintenance-maps_write-repeat"
            if referenced:
                data["processes"] = [row for row in data["processes"] if row["role"] != role]
                for suffix in (".command.json", ".stdout.txt", ".stderr.txt", ".nested.json"):
                    (path.parent / (role + suffix)).unlink()
                data["nested_processes"] = [row for row in data["nested_processes"] if row["parent_role"] != role]
                data["nested_expectations"] = [row for row in data["nested_expectations"] if row["parent_role"] != role]
                case = next(row for row in data["cases"] if row["id"] == "data.maintenance.maps_write")
                case["evidence"] = [name for name in case["evidence"] if not name.startswith(role + ".")]
            else:
                data["cases"][0]["evidence"] = [name for name in data["cases"][0]["evidence"] if not name.endswith(".command.json")]
            self.refresh(path, data)
            with self.assertRaisesRegex(ValueError, "command|launch"):
                self.parse(path)
