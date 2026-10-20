"""Fail closed when an installed-artifact proof is stale, redirected or incomplete."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from support import ROOT

SCRIPT = ROOT / ".agents/skills/verify-twinaatma/scripts/artifact.py"
spec = importlib.util.spec_from_file_location("installed_artifact", SCRIPT)
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


class InstalledArtifactTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "work/gc-artifacts/.knowledgeos/installed-host-20261019/artifact-worker/tests"
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.contents = {"knowledgeos/__init__.py": b"VALUE = 7\n", "knowledgeos/current.py": b"VALUE = 8\n", "AGENTS.md": b"Human identity requires human approval.\n", ".cursor/hooks/start.py": b"print('context')\n"}
        self.current = {p: hashlib.sha256(data).hexdigest() for p, data in self.contents.items()}

    def wheel(self, replace=None, omit=None, extra=None):
        path = self.directory / "candidate.whl"
        contents = dict(self.contents)
        contents.update(replace or {})
        contents.update(extra or {})
        contents.pop(omit, None)
        with zipfile.ZipFile(path, "w") as archive:
            for relative, data in contents.items():
                name = relative if relative.startswith("knowledgeos/") else "knowledgeos/_assets/" + relative
                archive.writestr(name, data)
        return path

    def test_wheel_requires_current_modules_and_bundled_instructions_and_hooks(self):
        self.assertTrue(artifact.wheel_binding(self.wheel(), self.current))
        for relative in ("knowledgeos/current.py", "AGENTS.md", ".cursor/hooks/start.py"):
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, "Stale|inventory"):
                    artifact.wheel_binding(self.wheel(replace={relative: b"old"}), self.current)
                with self.assertRaises(ValueError):
                    artifact.wheel_binding(self.wheel(omit=relative), self.current)

    def test_removed_modules_and_duplicate_wheel_members_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "inventory"):
            artifact.wheel_binding(self.wheel(extra={"knowledgeos/removed.py": b"old"}), self.current)
        path = self.wheel()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("knowledgeos/current.py", b"override")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            artifact.wheel_binding(path, self.current)

    def installation(self):
        environment = self.directory / "venv"
        package = environment / "Lib/site-packages/knowledgeos"
        package.mkdir(parents=True)
        for relative, data in self.contents.items():
            path = package / (Path(relative).name if relative.startswith("knowledgeos/") else "_assets/" + relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return environment, package

    def test_import_origin_must_be_current_isolated_site_packages(self):
        environment, package = self.installation()
        origin = package / "__init__.py"
        self.assertEqual(artifact.installed_origin(origin, environment, self.current), origin.resolve())
        with self.assertRaisesRegex(ValueError, "retained isolated"):
            artifact.installed_origin(ROOT / "knowledgeos/__init__.py", environment, self.current)
        (package / "current.py").write_bytes(b"stale installed module")
        with self.assertRaisesRegex(ValueError, "differ"):
            artifact.installed_origin(origin, environment, self.current)

    def test_linked_import_origin_is_rejected(self):
        environment, package = self.installation()
        target = self.directory / "outside.py"
        target.write_bytes(self.contents["knowledgeos/__init__.py"])
        origin = package / "redirected.py"
        try:
            origin.symlink_to(target)
        except OSError as exc:
            self.skipTest("Symlink creation unavailable: " + str(exc))
        with self.assertRaisesRegex(ValueError, "Linked"):
            artifact.installed_origin(origin, environment, self.current)

    def manifest(self):
        distribution = self.directory / "distribution"
        distribution.mkdir()
        executable = distribution / "twinaatma.exe"
        executable.write_bytes(b"synthetic frozen fixture")
        (distribution / "dependency.dll").write_bytes(b"full distribution member")
        data = {"producer": "verify-twinaatma.build/v1", "product_hashes": self.current, "inputs": self.current,
                "outputs": artifact.distribution_files(distribution), "distribution_root": str(distribution),
                "executable": str(executable), "build_commands": [{"command": ["builder", "fixture"], "exit_code": 0}]}
        manifest = self.directory / "build.json"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        return executable, manifest, data

    def test_binary_requires_current_build_inputs_and_complete_outputs(self):
        executable, manifest, data = self.manifest()
        root, inventory = artifact.binary_binding(executable, manifest, self.current)
        self.assertEqual(root, executable.parent)
        self.assertEqual(set(inventory), {"twinaatma.exe", "dependency.dll"})
        with self.assertRaisesRegex(ValueError, "require"):
            artifact.binary_binding(executable, None, self.current)
        stale = dict(data, inputs={})
        manifest.write_text(json.dumps(stale), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inputs"):
            artifact.binary_binding(executable, manifest, self.current)
        manifest.write_text(json.dumps(data), encoding="utf-8")
        (root / "dependency.dll").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            artifact.binary_binding(executable, manifest, self.current)

    def test_binary_manifest_rejects_added_members_and_failed_builds(self):
        executable, manifest, data = self.manifest()
        data["build_commands"][0]["exit_code"] = 1
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "successful"):
            artifact.binary_binding(executable, manifest, self.current)
        data["build_commands"][0]["exit_code"] = 0
        manifest.write_text(json.dumps(data), encoding="utf-8")
        (executable.parent / "unexpected.dll").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            artifact.binary_binding(executable, manifest, self.current)

    def test_binary_internal_links_require_manifest_and_external_links_are_refused(self):
        executable, manifest, data = self.manifest()
        link = executable.parent / "linked-dependency.dll"
        try:
            link.symlink_to("dependency.dll")
        except OSError as exc:
            self.skipTest("Symlink creation unavailable: " + str(exc))
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            artifact.binary_binding(executable, manifest, self.current)
        data["links"] = {"linked-dependency.dll": "dependency.dll"}
        manifest.write_text(json.dumps(data), encoding="utf-8")
        artifact.binary_binding(executable, manifest, self.current)
        external = self.directory / "external.dll"
        external.write_bytes(b"outside")
        link.unlink()
        link.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "escapes"):
            artifact.binary_binding(executable, manifest, self.current)
        link.unlink()
        link.symlink_to("missing.dll")
        with self.assertRaisesRegex(ValueError, "Dangling"):
            artifact.binary_binding(executable, manifest, self.current)
    def test_driver_refuses_output_outside_excluded_task_tree(self):
        executable = self.directory / "fixture.exe"
        executable.write_bytes(b"fixture")
        with self.assertRaisesRegex(ValueError, "Output"):
            artifact.ArtifactRun(ROOT / "outputs/uncontained-artifact-proof", executable, "binary")


if __name__ == "__main__":
    unittest.main()
