"""Controls for the single host-chat batch binding. No test starts a model, a host or a chat."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/verify-twinaatma/scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import host_freeze as fz  # noqa: E402

batch = load("host_batch_controls", "host_batch.py")
adapter = load("advanced_host_acceptance_controls", "advanced_host_acceptance.py")
HOST = {"cli": str(Path(sys.executable).resolve()), "cli_sha256": batch.sha(sys.executable), "version": "codex-cli 9.9.9",
        "configured_model": "model-x"}


class FakeRoot(unittest.TestCase):
    """A tiny checkout with a sealed, pinned freeze folder."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        for name, text in {"knowledgeos/a.py": "a = 1\n", "knowledgeos/b.py": "b = 2\n", "scripts/s.py": "s = 3\n",
                           "Templates/t.md": "# t\n", ".cursor/hooks/h.py": "h = 4\n"}.items():
            self.write(name, text)
        for name in fz.ROOT_INPUTS:
            self.write(name, name + "\n")
        shutil.copyfile(ROOT / batch.RUBRIC_RELATIVE, self.place(batch.RUBRIC_RELATIVE))
        self.pin = Path(self.temp.name) / "pin.json"
        self.freeze("freeze-a")

    def place(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, relative, text):
        self.place(relative).write_text(text, encoding="utf-8", newline="")

    def freeze(self, name, *, pin=True):
        self.base = self.root / batch.KNOWLEDGE / name
        self.base.mkdir(parents=True)
        batch.write_freeze(self.base, root=self.root, revision="rev-" + name)
        for support in fz.SUPPORT_NAMES:
            target = self.base / support
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(support + " " + name + "\n", encoding="utf-8", newline="")
        _path, self.seal_sha256 = batch.seal(self.base)
        if pin:
            fz.write_pin(self.pin, "work/gc-artifacts/.knowledgeos/" + name, self.seal_sha256, HOST)
        return self.binding() if pin else None

    def binding(self):
        return fz.load_binding(self.root, self.pin)


class BindingControls(FakeRoot):
    def test_staged_producer_refuses_an_added_product_input(self):
        shutil.copyfile(SCRIPTS / "host_freeze.py", self.place(".agents/skills/verify-twinaatma/scripts/host_freeze.py"))
        shutil.copyfile(SCRIPTS / "staged/advanced_host.py", self.base / "advanced_host.py")
        (self.base / "expectations.json").write_text(json.dumps({"rubric_sha256": batch.sha(self.root / batch.RUBRIC_RELATIVE)}), encoding="utf-8")
        (self.base / "private/input.json").write_text(json.dumps({"forbidden": {}}), encoding="utf-8")
        (self.base / "prepared.json").write_text(json.dumps({
            "expectations_sha256": batch.sha(self.base / "expectations.json"),
            "private_input_sha256": batch.sha(self.base / "private/input.json")}), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("staged_freeze_control", self.base / "advanced_host.py")
        staged = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(staged)
        self.write("knowledgeos/new.py", "added after preparation\n")
        with self.assertRaisesRegex((RuntimeError, ValueError), "frozen manifest|file set changed"):
            staged.Journey(self.base / fz.FREEZE_NAME, "synthetic test; no authority")
        self.assertEqual(list(self.base.glob("native-*")), [])

    def test_counts_come_from_the_freeze_and_the_tree(self):
        first = self.binding()
        self.assertEqual(first.source_input_count, len(fz.toolkit_inputs(self.root)))
        self.write("knowledgeos/c.py", "c = 5\n")
        second = self.freeze("freeze-b")
        self.assertEqual(second.source_input_count, first.source_input_count + 1)
        self.assertEqual(fz.check_product(second.product, self.root), second.source_input_count)

    def test_toolkit_inputs_match_the_independent_enumeration_in_acceptance(self):
        acceptance = load("acceptance_enumeration_control", "acceptance.py")
        self.assertEqual(fz.toolkit_inputs(ROOT), acceptance.data_toolkit_hashes())

    def test_hardlinked_product_input_is_refused(self):
        (self.root / "untracked-alias.py").hardlink_to(self.root / "knowledgeos/a.py")
        with self.assertRaisesRegex(fz.BindingError, "single-link"):
            fz.check_product(self.binding().product, self.root)

    def test_swapped_freeze_is_refused(self):
        other = self.base.with_name("other")
        other.mkdir()
        batch.write_freeze(other, root=self.root, revision="other")
        shutil.copyfile(other / fz.FREEZE_NAME, self.base / fz.FREEZE_NAME)
        with self.assertRaisesRegex(fz.BindingError, "freeze changed or was swapped"):
            self.binding()

    def test_swapped_seal_is_refused_by_the_pin(self):
        shutil.copyfile(self.base / fz.SEAL_NAME, self.base / "seal.copy")
        (self.base / fz.SEAL_NAME).write_text((self.base / "seal.copy").read_text(encoding="utf-8").replace("support", "supporT"), encoding="utf-8")
        with self.assertRaisesRegex(fz.BindingError, "seal changed or was swapped"):
            self.binding()

    def test_pin_to_another_folder_needs_that_folders_seal(self):
        self.freeze("freeze-b", pin=False)
        fz.write_pin(self.pin, "work/gc-artifacts/.knowledgeos/freeze-b", self.seal_sha256, HOST)
        self.assertEqual(self.binding().base.name, "freeze-b")
        fz.write_pin(self.pin, "work/gc-artifacts/.knowledgeos/freeze-b", "0" * 64, HOST)
        with self.assertRaises(fz.BindingError):
            self.binding()
        for bad in ("work/gc-artifacts/.knowledgeos/../x", "elsewhere/freeze-b", "work/gc-artifacts/.knowledgeos/a/b"):
            fz.write_pin(self.pin, bad, self.seal_sha256, HOST)
            with self.assertRaisesRegex(fz.BindingError, "pin is malformed"):
                self.binding()

    def test_missing_pin_is_refused(self):
        self.pin.unlink()
        with self.assertRaisesRegex(fz.BindingError, "No host freeze is pinned"):
            self.binding()

    def test_swapped_preparation_is_refused(self):
        binding = self.binding()
        fz.check_support(binding)
        (self.base / "expectations.json").write_text("weaker expectations\n", encoding="utf-8")
        with self.assertRaisesRegex(fz.BindingError, "changed after sealing"):
            fz.check_support(self.binding())

    def test_stale_product_is_refused(self):
        binding = self.binding()
        self.write("knowledgeos/a.py", "a = 'changed'\n")
        with self.assertRaisesRegex(fz.BindingError, "product changed"):
            fz.check_product(binding.product, self.root)
        self.write("knowledgeos/a.py", "a = 1\n")
        self.write("knowledgeos/new.py", "new = 1\n")
        with self.assertRaisesRegex(fz.BindingError, "file set changed"):
            fz.check_product(binding.product, self.root)

    def test_freeze_schema_is_strict(self):
        path = self.base / fz.FREEZE_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        for change in ({"new_live_model_authorization": True}, {"fixed_target": 53}, {"schema": "other"}, {"extra": 1},
                       {"rubric_sha256": "0" * 64}):
            path.write_text(json.dumps({**data, **change}), encoding="utf-8")
            with self.assertRaisesRegex(fz.BindingError, "fixed schema"):
                fz.freeze_product(path)


class AuthorizationControls(unittest.TestCase):
    def record(self, **change):
        record = {"status": "approved", "product_freeze_sha256": "f" * 64, "payload_inventory_sha256": "e" * 64,
                  "allowed_units": {unit: 3 for unit in fz.UNITS}, "maximum_model_conversations": 9,
                  "direct_user_reply": "yes"}
        record.update(change)
        return record

    def problem(self, record, **kw):
        return fz.authorization_problem(record, "f" * 64, "e" * 64, **kw)

    def test_bound_record_is_accepted(self):
        self.assertIsNone(self.problem(self.record(), maximum=9))
        self.assertIsNone(self.problem(self.record(allowed_units={"advanced-source": 3}), units=("advanced-source",)))

    def test_every_binding_field_is_required(self):
        for change in ({"status": None}, {"status": "pending"}, {"product_freeze_sha256": "0" * 64},
                       {"payload_inventory_sha256": "0" * 64}, {"allowed_units": {"installed-wheel": 3}},
                       {"allowed_units": {unit: True for unit in fz.UNITS}}, {"allowed_units": {unit: 2 for unit in fz.UNITS}},
                       {"direct_user_reply": ""}, {"direct_user_reply": None}, {"maximum_model_conversations": 8}):
            self.assertIsNotNone(self.problem(self.record(**change), maximum=9), change)
        self.assertIsNotNone(self.problem(None))


class StandaloneProducerControls(unittest.TestCase):
    def test_standalone_run_refuses_before_constructing_a_journey_or_starting_a_process(self):
        staged = load("standalone_host_route_control", "staged/advanced_host.py")
        argv = [str(SCRIPTS / "staged/advanced_host.py"), "--run", "--expected-product",
                "synthetic-freeze.json", "--root-authorization", "synthetic-no-authority",
                "--codex", "synthetic-never-executed.exe"]
        error = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(staged, "Journey") as journey, \
                mock.patch.object(staged.subprocess, "Popen") as popen, \
                mock.patch.object(staged.subprocess, "run") as run, contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as stop:
                staged.main()
        self.assertEqual(stop.exception.code, 2)
        self.assertIn("host_batch.py", error.getvalue())
        journey.assert_not_called()
        popen.assert_not_called()
        run.assert_not_called()


class ChatStepControls(FakeRoot):
    def prepare_check(self, authorize=False, **change):
        """A home folder with a user config, the inventory the check reads, and the optional record."""
        home = Path(self.temp.name) / "home"
        (home / ".codex").mkdir(parents=True, exist_ok=True)
        (home / ".codex/config.toml").write_text('model = "model-x"\n', encoding="utf-8")
        binding = self.binding()
        inventory = {"product_freeze_sha256": binding.frozen_sha256, "maximum_model_conversations": 9,
                     "allowed_units": {unit: 3 for unit in fz.UNITS},
                     "destination": {"user_configuration_sha256": batch.sha(home / ".codex/config.toml")},
                     "units": [{"unit": unit} for unit in fz.UNITS]}
        (self.base / "outbound-payload-review.json").write_text(json.dumps(inventory), encoding="utf-8")
        _path = self.base / fz.SEAL_NAME
        _path.unlink()
        _p, self.seal_sha256 = batch.seal(self.base)
        fz.write_pin(self.pin, "work/gc-artifacts/.knowledgeos/freeze-a", self.seal_sha256, HOST)
        if authorize:
            self.authorize(**change)
        return home

    def authorize(self, **change):
        binding = self.binding()
        record = {"status": "approved", "product_freeze_sha256": binding.frozen_sha256,
                  "payload_inventory_sha256": binding.inventory_sha256, "allowed_units": {unit: 3 for unit in fz.UNITS},
                  "maximum_model_conversations": 9, "direct_user_reply": "yes", "model": "model-x",
                  "single_use": True, "automatic_retries": False, "recorded_ns": 1}
        record.update(change)
        (self.base / batch.AUTHORIZATION).write_text(json.dumps(record), encoding="utf-8")

    def common(self, home):
        with mock.patch.object(Path, "home", return_value=home):
            return batch.common_check(root=self.root, pin_path=self.pin)

    def test_missing_authorization_refuses_before_any_process(self):
        home = self.prepare_check()
        with mock.patch.object(batch.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(fz.BindingError, "No human trial authorization"):
                with mock.patch.object(Path, "home", return_value=home):
                    batch.run_batch(HOST["cli"], root=self.root, pin_path=self.pin)
            with self.assertRaisesRegex(fz.BindingError, "No human trial authorization"):
                with mock.patch.object(Path, "home", return_value=home):
                    batch.run_unit("advanced-source", HOST["cli"], root=self.root, pin_path=self.pin)
        popen.assert_not_called()
        self.assertFalse((self.base / "batch-claim.json").exists())

    def test_authorization_for_another_freeze_refuses(self):
        home = self.prepare_check(authorize=True, product_freeze_sha256="0" * 64)
        with self.assertRaisesRegex(fz.BindingError, "different product freeze"):
            self.common(home)

    def test_authorization_for_another_payload_refuses(self):
        home = self.prepare_check(authorize=True, payload_inventory_sha256="0" * 64)
        with self.assertRaisesRegex(fz.BindingError, "different payload inventory"):
            self.common(home)

    def test_authorization_must_be_single_use_and_for_the_pinned_model(self):
        for change in ({"single_use": False}, {"automatic_retries": True}, {"model": "other"}, {"recorded_ns": None}):
            home = self.prepare_check(authorize=True, **change)
            with self.assertRaisesRegex(fz.BindingError, "single use"):
                self.common(home)
            (self.base / batch.AUTHORIZATION).unlink()

    def test_bound_authorization_passes_the_check_and_starts_nothing(self):
        home = self.prepare_check(authorize=True)
        with mock.patch.object(batch.subprocess, "Popen") as popen:
            binding, inventory, authorization = self.common(home)
        popen.assert_not_called()
        self.assertEqual(authorization["status"], "approved")
        self.assertEqual(list(inventory["allowed_units"]), list(fz.UNITS))

    def test_stale_product_refuses_the_chat_step(self):
        home = self.prepare_check(authorize=True)
        self.write("knowledgeos/b.py", "b = 'edited after freeze'\n")
        with self.assertRaisesRegex(fz.BindingError, "product changed"):
            self.common(home)

    def test_changed_destination_config_refuses(self):
        home = self.prepare_check(authorize=True)
        (home / ".codex/config.toml").write_text('model = "model-y"\n', encoding="utf-8")
        with self.assertRaisesRegex(fz.BindingError, "configured model or destination changed"):
            self.common(home)

    def test_a_second_batch_claim_is_refused(self):
        home = self.prepare_check(authorize=True)
        (self.base / "batch-claim.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(batch.subprocess, "Popen") as popen, mock.patch.object(Path, "home", return_value=home), \
                mock.patch.object(batch, "check_codex", return_value=HOST["cli"]):
            with self.assertRaises(FileExistsError):
                batch.run_batch(HOST["cli"], root=self.root, pin_path=self.pin)
        popen.assert_not_called()

    def test_chat_commands_need_the_explicit_flag(self):
        for command in (["chats", "--codex", HOST["cli"]], ["unit", "advanced-source", "--codex", HOST["cli"]]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
                batch.main(command)
            self.assertEqual(stop.exception.code, 2)

    def test_authorization_template_is_never_valid_as_printed(self):
        template = batch.authorization_template(self.binding())
        self.assertIsNotNone(fz.authorization_problem(template, template["product_freeze_sha256"], template["payload_inventory_sha256"], maximum=9))


class LaunchGuardControls(FakeRoot):
    def ready_guard(self):
        home = ChatStepControls.prepare_check(self)
        inventory_path = self.base / "outbound-payload-review.json"
        inventory = fz.read_json(inventory_path)
        inventory["units"][0].update(prompts=[{"label": "capture", "text": "say hi"}],
                                     initial_synthetic_notes={"AGENTS.md": {"sha256": batch.sha(self.root / "AGENTS.md")}})
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        (self.base / fz.SEAL_NAME).unlink()
        _, digest = batch.seal(self.base)
        fz.write_pin(self.pin, "work/gc-artifacts/.knowledgeos/freeze-a", digest, HOST)
        ChatStepControls.authorize(self)
        binding = self.binding()
        authorization_sha = batch.sha(self.base / batch.AUTHORIZATION)
        batch.create(self.base / batch.claim_name("installed-wheel"), {
            "authorization_sha256": authorization_sha, "product_freeze_sha256": binding.frozen_sha256,
            "payload_inventory_sha256": binding.inventory_sha256, "unit": "installed-wheel",
            "maximum_model_conversations": 3, "wrapper_sha256": batch.sha(batch.__file__)})
        guard = batch.LaunchGuard(binding, inventory, authorization_sha, "installed-wheel")
        guard.server, guard.directory = {"command": "server", "args": []}, self.base / "run"
        project = self.base / "capture-project"
        (project / ".codex").mkdir(parents=True)
        shutil.copyfile(self.root / "AGENTS.md", project / "AGENTS.md")
        from knowledgeos.host_setup import render_codex_config
        server = {"command": sys.executable,
                  "args": ["-B", "-P", str(SCRIPTS / "host.py"), "--proxy", str(guard.directory / "capture.wire.jsonl"), "--", "server"],
                  "env": {"KNOWLEDGEOS_STATE_DIR": str(guard.directory / "gate-state"), "PYTHONDONTWRITEBYTECODE": "1"}}
        (project / ".codex/config.toml").write_text(render_codex_config({"mcp_servers": {"knowledgeos": server}}), encoding="utf-8")
        return guard, project, home

    def test_live_product_change_after_unit_initialization_refuses_before_reservation(self):
        guard, project, home = self.ready_guard()
        self.write("knowledgeos/a.py", "changed after the unit initialized\n")
        with mock.patch.object(Path, "home", return_value=home), self.assertRaisesRegex(fz.BindingError, "product changed"):
            guard.before_command("capture", batch.exec_argv(HOST["cli"], project, "model-x"), "say hi", project)
        self.assertEqual(list(self.base.glob("*.model-reservation.json")), [])

    def test_authorization_change_after_unit_initialization_refuses_before_reservation(self):
        guard, project, home = self.ready_guard()
        authorization = fz.read_json(self.base / batch.AUTHORIZATION)
        authorization["direct_user_reply"] = "different synthetic test record"
        (self.base / batch.AUTHORIZATION).write_text(json.dumps(authorization), encoding="utf-8")
        with mock.patch.object(Path, "home", return_value=home), self.assertRaisesRegex(fz.BindingError, "authorization changed"):
            guard.before_command("capture", batch.exec_argv(HOST["cli"], project, "model-x"), "say hi", project)
        self.assertEqual(list(self.base.glob("*.model-reservation.json")), [])

    def test_valid_launch_reserves_once_and_never_starts_a_process(self):
        guard, project, home = self.ready_guard()
        argv = batch.exec_argv(HOST["cli"], project, "model-x")
        with mock.patch.object(Path, "home", return_value=home), mock.patch.object(batch.subprocess, "Popen") as popen:
            guard.before_command("capture", argv, "say hi", project)
            with self.assertRaisesRegex(ValueError, "exhausted, repeated"):
                guard.before_command("capture", argv, "say hi", project)
        popen.assert_not_called()
        self.assertEqual(guard.started, ["capture"])
        self.assertEqual(len(list(self.base.glob("*.model-reservation.json"))), 1)

    def guard(self):
        binding = self.binding()
        unit = "installed-wheel"
        batch.create(binding.base / batch.claim_name(unit), {
            "authorization_sha256": "a" * 64, "product_freeze_sha256": binding.frozen_sha256,
            "payload_inventory_sha256": binding.inventory_sha256, "unit": unit, "maximum_model_conversations": 3,
            "wrapper_sha256": batch.sha(batch.__file__)})
        inventory = {"units": [{"unit": unit, "prompts": [{"label": "capture", "text": "say hi"}], "initial_synthetic_notes": {}}]}
        guard = batch.LaunchGuard(binding, inventory, "a" * 64, unit)
        guard.server, guard.directory = {"command": "x", "args": []}, binding.base
        return guard, binding

    def test_non_chat_commands_pass_and_chat_changes_are_refused(self):
        guard, binding = self.guard()
        guard.before_command("init", ["python", "-m", "knowledgeos", "init"], "", None)
        project = binding.base / "capture-project"
        good = batch.exec_argv(binding.host["cli"], project, binding.host["configured_model"])
        with self.assertRaisesRegex(ValueError, "prompt changed"):
            guard.before_command("capture", good, "say something else", project)
        with self.assertRaisesRegex(ValueError, "prompt changed"):
            guard.before_command("undeclared", good, "say hi", project)
        with self.assertRaisesRegex(ValueError, "invocation differs"):
            guard.before_command("capture", [*good[:-1], "other-model"], "say hi", project)
        with self.assertRaisesRegex(ValueError, "invocation differs"):
            guard.before_command("capture", [*good, "--dangerously-bypass-approvals-and-sandbox"], "say hi", project)
        self.assertEqual(guard.started, [])
        self.assertEqual(list(binding.base.glob("*.model-reservation.json")), [])

    def test_claim_for_another_authorization_is_refused(self):
        _guard, binding = self.guard()
        with self.assertRaisesRegex(ValueError, "claim is mismatched"):
            batch.LaunchGuard(binding, {"units": [{"unit": "installed-wheel", "prompts": [], "initial_synthetic_notes": {}}]},
                              "b" * 64, "installed-wheel")


class ZeroModelGuardControls(unittest.TestCase):
    def test_codex_chats_cannot_run_in_the_zero_model_helper(self):
        for argv in (["codex", "exec", "hi"], ["C:/x/codex.exe", "--disable", "apps", "exec", "--json"], ["codex.exe", "chat"]):
            with self.assertRaises(ValueError):
                batch.refuse_model_argv(argv)
        batch.refuse_model_argv(["codex", "--version"])
        batch.refuse_model_argv([sys.executable, "-B", "advanced_host.py", "--prepare"])

    def test_freeze_directory_must_be_a_direct_child_of_the_knowledge_folder(self):
        root = Path("C:/checkout")
        self.assertEqual(batch.freeze_directory("work/gc-artifacts/.knowledgeos/f1", root)[1], "work/gc-artifacts/.knowledgeos/f1")
        for bad in ("work/gc-artifacts/.knowledgeos", "work/gc-artifacts/.knowledgeos/a/b", "elsewhere/f1", "C:/other/f1"):
            with self.assertRaises(ValueError):
                batch.freeze_directory(bad, root)


class AdapterBindingControls(FakeRoot):
    """The grader reads its freeze only through the pin."""

    def setUp(self):
        super().setUp()
        self.patches = [mock.patch.object(adapter, "ROOT", self.root), mock.patch.object(adapter, "PIN_PATH", self.pin),
                        mock.patch.object(adapter, "RUBRIC", self.root / batch.RUBRIC_RELATIVE)]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def report(self):
        directory = self.base / "native-20261021-000000-00000000"
        directory.mkdir()
        (directory / "report.json").write_text("{}", encoding="utf-8")
        return directory / "report.json"

    def test_report_outside_the_pinned_folder_is_refused(self):
        elsewhere = self.base.with_name("elsewhere") / "native-20261021-000000-00000000"
        elsewhere.mkdir(parents=True)
        (elsewhere / "report.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside the trusted"):
            adapter.advanced_host_report(elsewhere / "report.json", {})

    def test_swapped_preparation_is_refused_by_the_grader(self):
        report = self.report()
        (self.base / "prepared.json").write_text("swapped\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "producer, support or literal expectations changed"):
            adapter.advanced_host_report(report, {})

    def test_stale_product_is_refused_by_the_grader(self):
        report = self.report()
        self.write("knowledgeos/a.py", "a = 'stale'\n")
        with self.assertRaisesRegex(ValueError, "stale against the complete frozen source inputs"):
            adapter.advanced_host_report(report, {})
        self.write("knowledgeos/a.py", "a = 1\n")
        self.write("knowledgeos/extra.py", "x = 1\n")
        with self.assertRaisesRegex(ValueError, "stale against the complete frozen source inputs"):
            adapter.advanced_host_report(report, {})

    def test_swapped_freeze_is_refused_by_the_grader(self):
        report = self.report()
        other = self.base.with_name("other")
        other.mkdir()
        batch.write_freeze(other, root=self.root, revision="other")
        shutil.copyfile(other / fz.FREEZE_NAME, self.base / fz.FREEZE_NAME)
        with self.assertRaisesRegex(ValueError, "swapped"):
            adapter.advanced_host_report(report, {})

    def claim_values(self, binding, authorization_sha256, directory):
        return {"authorization_sha256": authorization_sha256, "product_freeze_sha256": binding.frozen_sha256,
                "payload_inventory_sha256": binding.inventory_sha256, "directory": str(directory),
                "unit": "advanced-source", "maximum_model_conversations": 3, "claimed_ns": 50}

    def authorization(self, binding):
        return {"status": "approved", "product_freeze_sha256": binding.frozen_sha256,
                "payload_inventory_sha256": binding.inventory_sha256, "allowed_units": {"advanced-source": 3},
                "direct_user_reply": "synthetic test record", "maximum_model_conversations": 9,
                "single_use": True, "automatic_retries": False, "model": HOST["configured_model"], "recorded_ns": 1}

    def test_grader_refuses_changed_model_and_retry_authorization(self):
        binding = self.binding()
        claim = self.claim_values(binding, "d" * 64, self.base / "native-x")
        for change in ({"model": "other"}, {"single_use": False}, {"automatic_retries": True},
                       {"maximum_model_conversations": 10}, {"recorded_ns": None}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "does not bind"):
                self.check(binding, dict(self.authorization(binding), **change), claim)

    def check(self, binding, authorization, claim, *, first_model_ns=100, initialized_ns=10):
        digest = "d" * 64
        adapter.checked_authorization_values(
            self.base / "native-x", {"root_authorization": digest}, {"root_authorization": digest}, authorization, claim,
            digest, first_model_ns=first_model_ns, initialized_ns=initialized_ns, pin=binding)

    def test_authorization_and_single_use_claim_are_bound_to_the_pin(self):
        binding = self.binding()
        claim = self.claim_values(binding, "d" * 64, self.base / "native-x")
        self.check(binding, self.authorization(binding), claim)
        with self.assertRaisesRegex(ValueError, "does not bind"):
            self.check(binding, dict(self.authorization(binding), product_freeze_sha256="0" * 64), claim)
        with self.assertRaisesRegex(ValueError, "does not bind"):
            self.check(binding, dict(self.authorization(binding), payload_inventory_sha256="0" * 64), claim)
        with self.assertRaisesRegex(ValueError, "claim is absent, reused"):
            self.check(binding, self.authorization(binding), dict(claim, authorization_sha256="1" * 64))
        with self.assertRaisesRegex(ValueError, "claim is absent, reused"):
            self.check(binding, self.authorization(binding), dict(claim, directory=str(self.base / "native-y")))
        with self.assertRaisesRegex(ValueError, "claim is absent, reused"):
            self.check(binding, self.authorization(binding), claim, first_model_ns=40)

    def test_host_identity_comes_from_the_pin(self):
        binding = self.binding()
        record = {"command": ["codex", "--version"], "stdout_sha256": "0" * 64, "stopped": True, "exit_code": 0}
        with self.assertRaisesRegex(ValueError, "Actual host version, configured model or native mode differs"):
            adapter.checked_host_version({"name": "codex-cli", "version": "codex-cli 0.1.0", "configured_model": "model-x",
                                          "mode": "native ephemeral source host"}, record, [], None, binding)


if __name__ == "__main__":
    unittest.main()
