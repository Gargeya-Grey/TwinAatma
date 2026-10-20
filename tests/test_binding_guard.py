"""Binding-state failures preserve identity and existing durable state."""
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
PRODUCT = Path(os.environ.get("TWIN_BINDING_PRODUCT_ROOT", ROOT))
BASE = Path(os.environ.get("TWIN_BINDING_EVIDENCE_ROOT", ROOT / "work/gc-artifacts/.knowledgeos/binding-guard-tests"))


class BindingGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = BASE / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        cls.evidence.mkdir(parents=True)
        cls.processes = []

    @classmethod
    def tearDownClass(cls):
        (cls.evidence / "run.json").write_text(json.dumps({
            "product_root": str(PRODUCT), "processes": cls.processes,
            "all_started_processes_stopped": all(row["stopped"] for row in cls.processes),
        }, indent=2), encoding="utf-8")

    def fixture(self):
        scope = self.evidence / uuid.uuid4().hex[:8]
        vault = scope / "vault"
        vault.mkdir(parents=True)
        for name in ("knowledgeos", "scripts", "Templates", ".cursor/hooks"):
            shutil.copytree(PRODUCT / name, vault / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "README.md", "LICENSE", "pyproject.toml", "setup.py", "MANIFEST.in", "knowledgeos.config.example.json", "mcp.cursor.example.json"):
            shutil.copyfile(PRODUCT / name, vault / name)
        initialized = self.command(vault, ["-m", "knowledgeos", "init", str(vault), "--name", "Synthetic Binding Owner", "--force", "--non-interactive"], state=scope / "initial-state")
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
        return vault, scope / "binding-state"

    def environment(self, vault, state):
        env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(state), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        for name in ("KNOWLEDGEOS_VAULT", "KNOWLEDGEOS_GATE_KEY", "PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        return env

    def launch(self, vault, args, state):
        argv = [sys.executable, "-B", *args]
        child = subprocess.Popen(argv, cwd=vault, env=self.environment(vault, state), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        return child, {"argv": argv, "cwd": str(vault), "state": str(state), "test": self._testMethodName, "pid": child.pid}

    def finish(self, launched):
        child, row = launched
        timeout = False
        try:
            stdout, stderr = child.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            timeout = True
            child.kill()
            stdout, stderr = child.communicate(timeout=15)
        row.update(exit_code=child.returncode, stopped=child.poll() is not None, timed_out=timeout)
        stem = self.evidence / ("command-%03d" % len(self.processes))
        self.processes.append(row)
        stem.with_suffix(".command.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
        stem.with_suffix(".stdout.txt").write_text(stdout, encoding="utf-8")
        stem.with_suffix(".stderr.txt").write_text(stderr, encoding="utf-8")
        self.assertFalse(timeout, stdout + stderr)
        return subprocess.CompletedProcess(row["argv"], child.returncode, stdout, stderr)

    def command(self, vault, args, *, state):
        return self.finish(self.launch(vault, args, state))

    def pending(self, vault, state, prefix=""):
        if prefix:
            code = prefix + "\nfrom knowledgeos.__main__ import main\nraise SystemExit(main(['self', 'pending', '--vault', '.']))\n"
            return self.command(vault, ["-c", code], state=state)
        return self.command(vault, ["-m", "knowledgeos", "self", "pending", "--vault", str(vault)], state=state)

    def proposal(self, vault, state):
        return self.command(vault, ["-m", "knowledgeos", "memory", "memory_propose_self_update",
                            "--vault", str(vault), "--section", "heuristics", "--mode", "append",
                            "--summary", "Synthetic binding proposal",
                            "--proposed-markdown", "- Prefer explicit reports for this synthetic fixture.",
                            "--rationale", "Synthetic test proposal without approval."], state=state)

    def seeded(self, state):
        state.mkdir()
        binding = state / "vault-bindings.json"
        original = b'{"/independent/existing-vault": "1234567890abcdef"}\r\n'
        binding.write_bytes(original)
        return binding, original

    def symlink(self, source, destination, *, directory=False):
        try:
            destination.symlink_to(source, target_is_directory=directory)
        except OSError as exc:
            self.skipTest("Native symbolic links unavailable: " + str(exc))

    def test_public_pending_refuses_identity_hardlink(self):
        vault, state = self.fixture()
        state.mkdir()
        identity = vault / "People/Self.md"
        before = identity.read_bytes()
        binding = state / "vault-bindings.json"
        os.link(identity, binding)
        result = self.pending(vault, state)
        (vault.parent / "hardlink-observation.json").write_text(json.dumps({
            "exit_code": result.returncode, "identity_before_sha256": hashlib.sha256(before).hexdigest(),
            "identity_after_sha256": hashlib.sha256(identity.read_bytes()).hexdigest(),
            "binding_after_sha256": hashlib.sha256(binding.read_bytes()).hexdigest(),
        }, indent=2), encoding="utf-8")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), before)
        self.assertEqual(binding.read_bytes(), before)

    def test_pending_refuses_malformed_bindings_without_reset(self):
        malformed = (b'{"unfinished":', b'[]', b'{"/old": 3}', b'{"/old": ""}',
                     b'{"/old":"one", "/old":"two"}', b'\xff\xfe')
        for original in malformed:
            with self.subTest(payload=original):
                vault, state = self.fixture()
                state.mkdir()
                binding = state / "vault-bindings.json"
                binding.write_bytes(original)
                identity = (vault / "People/Self.md").read_bytes()
                result = self.pending(vault, state)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(binding.read_bytes(), original)
                self.assertEqual((vault / "People/Self.md").read_bytes(), identity)

    def test_pending_refuses_directory_binding(self):
        vault, state = self.fixture()
        binding = state / "vault-bindings.json"
        binding.mkdir(parents=True)
        (binding / "owner.txt").write_bytes(b"Keep this directory.\r\n")
        result = self.pending(vault, state)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((binding / "owner.txt").read_bytes(), b"Keep this directory.\r\n")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Native FIFO files are unavailable")
    def test_pending_refuses_fifo_binding_without_opening_it(self):
        vault, state = self.fixture()
        state.mkdir()
        binding = state / "vault-bindings.json"
        try:
            os.mkfifo(binding)
        except OSError as exc:
            if exc.errno in (errno.EOPNOTSUPP, errno.ENOSYS):
                self.skipTest("The fixture filesystem does not support native FIFO files: " + str(exc))
            raise
        result = self.pending(vault, state)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(binding.exists())

    def test_pending_refuses_identity_hardlinks_at_binding_lock_names(self):
        for name in ("vault-bindings.lock", "vault-bindings.lock.guard"):
            with self.subTest(name=name):
                vault, state = self.fixture()
                state.mkdir()
                identity = vault / "People/Self.md"
                before = identity.read_bytes()
                alias = state / name
                os.link(identity, alias)
                result = self.pending(vault, state)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(identity.read_bytes(), before)
                self.assertEqual(alias.read_bytes(), before)
                self.assertFalse((state / "vault-bindings.json").exists())

    def test_pending_refuses_symbolic_binding(self):
        vault, state = self.fixture()
        state.mkdir()
        identity = vault / "People/Self.md"
        before = identity.read_bytes()
        binding = state / "vault-bindings.json"
        self.symlink(identity, binding)
        result = self.pending(vault, state)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(identity.read_bytes(), before)
        self.assertTrue(binding.is_symlink())

    def test_pending_refuses_dangling_symbolic_binding(self):
        vault, state = self.fixture()
        state.mkdir()
        outside = vault.parent / "absent-outside.json"
        binding = state / "vault-bindings.json"
        self.symlink(outside, binding)
        result = self.pending(vault, state)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(outside.exists())
        self.assertTrue(binding.is_symlink())

    def test_pending_refuses_linked_state_directory(self):
        vault, state = self.fixture()
        outside = vault.parent / "retained-state"
        outside.mkdir()
        original = b'{"/independent/existing-vault":"1234567890abcdef"}\n'
        (outside / "vault-bindings.json").write_bytes(original)
        self.symlink(outside, state, directory=True)
        result = self.pending(vault, state)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((outside / "vault-bindings.json").read_bytes(), original)

    def test_replace_fault_preserves_bindings_and_retries(self):
        vault, state = self.fixture()
        binding, original = self.seeded(state)
        identity = (vault / "People/Self.md").read_bytes()
        prefix = ("import os, sys\nfrom unittest.mock import patch\nreplace = os.replace\n"
                  "def fail(source, destination):\n"
                  "    if str(destination).endswith('vault-bindings.json'):\n"
                  "        print('BINDING_FAULT_INJECTED=replace', file=sys.stderr)\n"
                  "        raise OSError('injected binding replace failure')\n"
                  "    return replace(source, destination)\n"
                  "patch.object(os, 'replace', fail).start()\n")
        result = self.pending(vault, state, prefix)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BINDING_FAULT_INJECTED=replace", result.stderr)
        self.assertIn("Remembering policy state is unavailable", result.stderr)
        self.assertNotIn("injected binding replace failure", result.stderr)
        self.assertEqual(binding.read_bytes(), original)
        self.assertEqual((vault / "People/Self.md").read_bytes(), identity)
        retry = self.pending(vault, state)
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        observed = json.loads(binding.read_bytes())
        self.assertEqual(observed["/independent/existing-vault"], "1234567890abcdef")
        self.assertEqual(len(observed), 2)

    def test_partial_write_fault_preserves_bindings_and_retries(self):
        vault, state = self.fixture()
        binding, original = self.seeded(state)
        identity = (vault / "People/Self.md").read_bytes()
        prefix = ("import io, os, sys\nfrom unittest.mock import patch\nfdopen = os.fdopen\nopening = io.open\n"
                  "class Broken:\n"
                  "    def __init__(self, handle): self.handle = handle\n"
                  "    def __enter__(self): self.handle.__enter__(); return self\n"
                  "    def __exit__(self, *args): return self.handle.__exit__(*args)\n"
                  "    def write(self, data):\n"
                  "        self.handle.write(data[:max(1, len(data)//2)])\n"
                  "        self.handle.flush()\n"
                  "        print('BINDING_FAULT_INJECTED=partial', file=sys.stderr)\n"
                  "        raise OSError('injected binding partial write failure')\n"
                  "def fail_fd(fd, mode, *args, **kwargs):\n"
                  "    handle = fdopen(fd, mode, *args, **kwargs)\n"
                  "    return Broken(handle) if mode == 'wb' else handle\n"
                  "def fail_open(path, mode='r', *args, **kwargs):\n"
                  "    handle = opening(path, mode, *args, **kwargs)\n"
                  "    return Broken(handle) if str(path).endswith('vault-bindings.json') and mode == 'w' else handle\n"
                  "patch.object(os, 'fdopen', fail_fd).start()\n"
                  "patch.object(io, 'open', fail_open).start()\n")
        result = self.pending(vault, state, prefix)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BINDING_FAULT_INJECTED=partial", result.stderr)
        self.assertIn("Remembering policy state is unavailable", result.stderr)
        self.assertNotIn("injected binding partial write failure", result.stderr)
        self.assertEqual(binding.read_bytes(), original)
        self.assertEqual((vault / "People/Self.md").read_bytes(), identity)
        retry = self.pending(vault, state)
        self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
        self.assertEqual(len(json.loads(binding.read_bytes())), 2)

    def test_concurrent_public_pending_merges_two_vaults(self):
        first, state = self.fixture()
        second, _ = self.fixture()
        binding, _ = self.seeded(state)
        barriers = first.parent / "barriers"
        barriers.mkdir()
        before = [(vault / "People/Self.md").read_bytes() for vault in (first, second)]
        launches = []
        for index, vault in enumerate((first, second)):
            prefix = ("import io, time\nfrom pathlib import Path\nfrom unittest.mock import patch\n"
                      f"barriers = Path({str(barriers)!r})\nopening = io.open\n"
                      "def delayed(path, mode='r', *args, **kwargs):\n"
                      "    if str(path).endswith('vault-bindings.json') and mode == 'w':\n"
                      f"        (barriers / 'writer-{index}').touch()\n"
                      "        deadline = time.monotonic() + 15\n"
                      "        while len(list(barriers.glob('writer-*'))) < 2:\n"
                      "            if time.monotonic() >= deadline: raise RuntimeError('binding race barrier timed out')\n"
                      "            time.sleep(0.01)\n"
                      "    return opening(path, mode, *args, **kwargs)\n"
                      "patch.object(io, 'open', delayed).start()\n"
                      "from knowledgeos.__main__ import main\n"
                      "raise SystemExit(main(['self', 'pending', '--vault', '.']))\n")
            launches.append(self.launch(vault, ["-c", prefix], state))
        results = [self.finish(launched) for launched in launches]
        for result in results:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = {"/independent/existing-vault": "1234567890abcdef"}
        for vault in (first, second):
            marker = json.loads((vault / ".knowledgeos-vault.json").read_bytes())
            expected[str(vault.resolve())] = marker["vault_id"][:16]
        self.assertEqual(json.loads(binding.read_bytes()), expected)
        for vault, original in zip((first, second), before):
            self.assertEqual((vault / "People/Self.md").read_bytes(), original)

    def test_normal_pending_proposal_and_repeated_read_preserve_identity(self):
        vault, state = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        pending = self.pending(vault, state)
        self.assertEqual(pending.returncode, 0, pending.stdout + pending.stderr)
        self.assertIn("No Self proposals waiting for you.", pending.stdout)
        marker = json.loads((vault / ".knowledgeos-vault.json").read_bytes())
        binding = state / "vault-bindings.json"
        self.assertEqual(json.loads(binding.read_bytes()), {str(vault.resolve()): marker["vault_id"][:16]})
        stable_bytes = binding.read_bytes()
        proposed = self.proposal(vault, state)
        self.assertEqual(proposed.returncode, 0, proposed.stdout + proposed.stderr)
        response = json.loads(proposed.stdout)
        self.assertTrue(response.get("ok"), response)
        observed = self.pending(vault, state)
        self.assertEqual(observed.returncode, 0, observed.stdout + observed.stderr)
        self.assertIn(response["proposal_path"], observed.stdout)
        self.assertEqual((vault / "People/Self.md").read_bytes(), original)
        self.assertEqual(binding.read_bytes(), stable_bytes)

    def test_moved_vault_retains_proposals_and_binding_survives_marker_change(self):
        vault, state = self.fixture()
        original = (vault / "People/Self.md").read_bytes()
        proposed = self.proposal(vault, state)
        self.assertEqual(proposed.returncode, 0, proposed.stdout + proposed.stderr)
        proposal = json.loads(proposed.stdout)["proposal_path"]
        marker = json.loads((vault / ".knowledgeos-vault.json").read_bytes())
        old_key = marker["vault_id"][:16]
        old_path = str(vault.resolve())
        moved = vault.with_name("moved-vault")
        vault.rename(moved)
        result = self.pending(moved, state)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(proposal, result.stdout)
        self.assertEqual(json.loads((state / "vault-bindings.json").read_bytes()),
                         {old_path: old_key, str(moved.resolve()): old_key})
        marker["vault_id"] = "fedcba0987654321" * 2
        (moved / ".knowledgeos-vault.json").write_bytes(json.dumps(marker).encode())
        after_marker = self.pending(moved, state)
        self.assertEqual(after_marker.returncode, 0, after_marker.stdout + after_marker.stderr)
        self.assertIn(proposal, after_marker.stdout)
        self.assertEqual(json.loads((state / "vault-bindings.json").read_bytes())[str(moved.resolve())], old_key)
        self.assertEqual((moved / "People/Self.md").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
