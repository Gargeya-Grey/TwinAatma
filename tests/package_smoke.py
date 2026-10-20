"""Verify the explicit artifact passed in, never a hard-coded previous build.

python tests/package_smoke.py --wheel path/to/build.whl --source path/to/source
python tests/package_smoke.py --binary path/to/twinaatma.exe
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import venv
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    artifact = parser.add_mutually_exclusive_group(required=True)
    artifact.add_argument("--wheel", type=Path)
    artifact.add_argument("--binary", type=Path)
    parser.add_argument("--source", type=Path, help="check wheel product bytes against this tree")
    args = parser.parse_args()
    path = (args.wheel or args.binary).resolve(strict=True)
    results = []

    def check(name, condition):
        results.append({"check": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory(prefix="ta-artifact-") as tmp:
        root = Path(tmp)
        env = {**os.environ, "KNOWLEDGEOS_STATE_DIR": str(root / "state"),
               "PYTHONIOENCODING": "utf-8"}
        env.pop("PYTHONPATH", None)
        env.pop("KNOWLEDGEOS_VAULT", None)
        if args.wheel:
            with zipfile.ZipFile(path) as wheel:
                check("tests are not shipped", not any(n.startswith("tests/") for n in wheel.namelist()))
                check("starter kit is shipped", "knowledgeos/_assets/AGENTS.md" in wheel.namelist())
                if args.source:
                    for source in sorted((args.source / "knowledgeos").glob("*.py")):
                        check(f"current source bytes: {source.name}",
                              wheel.read("knowledgeos/" + source.name) == source.read_bytes())
            venv.EnvBuilder(with_pip=True).create(root / "venv")
            py = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            install = subprocess.run([str(py), "-m", "pip", "install", "--no-index", "--no-deps", str(path)],
                                     cwd=root, env=env, capture_output=True, text=True, timeout=300)
            check("wheel installs", install.returncode == 0)
            location = subprocess.run([str(py), "-c", "import knowledgeos; print(knowledgeos.__file__)"],
                                      cwd=root, env=env, capture_output=True, text=True, timeout=30)
            check("imports installed package, not checkout", "site-packages" in location.stdout)
            executable = py.with_name("twinaatma.exe" if os.name == "nt" else "twinaatma")
        else:
            executable = path

        def run(*argv):
            proc = subprocess.run([str(executable), *map(str, argv)], cwd=root, env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=180)
            check("command succeeds: " + " ".join(map(str, argv[:2])), proc.returncode == 0)
            return proc.stdout

        run("version")
        vault = root / "vault"
        created = json.loads(run("init", vault, "--name", "Smoke", "--non-interactive"))
        check("init reports no failed post-init steps", '"ok": false' not in json.dumps(created))
        check("identity exists", (vault / "People" / "Self.md").is_file())
        self_before = (vault / "People" / "Self.md").read_bytes()
        run("doctor", "--vault", vault)
        run("validate", "--vault", vault)
        run("breathe", "--vault", vault, "--prewarm")

        note = vault / "Concepts" / "Deployment runbook.md"
        note.write_bytes(b"---\ntype: concept\ndescription:\n  - cost\n  - risk\n---\n\nquartzite\n")
        for query in ("Deployment", "Depl", "runbook", "quartzite"):
            result = json.loads(run("memory", "memory_search", "--vault", vault, "--query", query))
            row = next((r for r in result.get("ranked", []) if r["path"] == "Concepts/Deployment runbook.md"), None)
            check("finds current ordinary note: " + query, row is not None)
            check("derived title is displayed: " + query, row["title"] == "Deployment runbook")
            check("normal notes do not freeze the index: " + query, not result.get("index_frozen"))

        hooks = json.loads((vault / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        start = hooks["hooks"]["sessionStart"][0]["command"]
        end = hooks["hooks"]["sessionEnd"][0]["command"]
        marker = root / "vault-code-ran"
        hooks_dir = vault / ".cursor" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        for name in ("twin_session_start.py", "json.py"):
            (hooks_dir / name).write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
        warmup_note = vault / "Inbox" / "Generated hook warmup.md"
        warmup_note.write_text("---\ntype: concept\ntitle: Generated hook warmup\nstatus: active\n"
                               "schema: knowledgeos-v0.2\n---\n\nsmoke-hook-quartzite\n", encoding="utf-8")
        hook = subprocess.run(start, shell=True, cwd=vault, env=env, input='{"hook_event_name":"sessionStart"}',
                              capture_output=True, text=True, encoding="utf-8", timeout=180)
        check("start hook runs", hook.returncode == 0)
        context = json.loads(hook.stdout).get("additional_context", "")
        check("start hook returns agent context", "memory_session_start" in context)
        check("start hook reports successful warmup", "rebuilt_index" in context and "Pre-warm unavailable" not in context)
        with closing(sqlite3.connect(vault / "knowledge_index.db")) as connection:
            row = connection.execute("SELECT body FROM notes_fts WHERE path = ?",
                                     ("Inbox/Generated hook warmup.md",)).fetchone()
        check("start hook actually indexes the new note", row is not None and "smoke-hook-quartzite" in row[0])
        sessions = []
        for session_id in ("package-smoke-first", "package-smoke-second"):
            opened = json.loads(run("memory", "memory_session_start", "--vault", vault,
                                    "--args", json.dumps({"session_id": session_id, "task_hint": "Package smoke"})))
            check("genuine session ID is retained: " + session_id, opened.get("session_id") == session_id)
            sessions.append(session_id)
        event = json.dumps({"memory_session_id": sessions[0]})
        ended = subprocess.run(end, shell=True, cwd=vault, env=env, input=event,
                               capture_output=True, text=True, encoding="utf-8", timeout=180)
        check("end hook runs", ended.returncode == 0)
        state_path = vault / ".knowledgeos" / "autopilot.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        check("end hook targets the named session", state["sessions"][sessions[0]]["status"] == "orphaned"
              and state["sessions"][sessions[1]]["status"] == "open" and state["real_sessions"] == 2)
        repeated = subprocess.run(end, shell=True, cwd=vault, env=env, input=event,
                                  capture_output=True, text=True, encoding="utf-8", timeout=180)
        check("repeated end hook runs", repeated.returncode == 0)
        check("repeated end hook is idempotent", json.loads(state_path.read_text(encoding="utf-8")) == state)
        check("vault hook code cannot run", not marker.exists())
        check("identity was not changed", (vault / "People" / "Self.md").read_bytes() == self_before)

    print(json.dumps({"artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "python": platform.python_version(), "platform": sys.platform,
                      "checks": results, "passed": len(results)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
