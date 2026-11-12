"""Drive a new person's first day through the real command line and the real MCP server.

usage: python -B .agents/skills/verify-twinaatma/scripts/first_day.py --output <new-dir>

Builds a synthetic vault below <new-dir>, with its own state folder. No model call and no
host is involved, so a pass here is not host acceptance. It prints one PASS or FAIL line per
check, writes `report.json`, and exits 1 when a check fails.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SECRET = "sk-live-9f8e7d6c5b4a39281706f5e4d3c2b1a0"
EXPORT = f"""# What my other assistant remembers about me

## Work
- Works as a backend engineer on a billing platform in Pune.
- Prefers Postgres over MongoDB for anything with money in it.
- Always wants code examples in Python with type hints.
- Never schedules meetings before ten in the morning.

## Family
- Daughter Mira was born on March 14 and loves dinosaurs.

## Accounts
- My API key is {SECRET} for the payments account.
"""
FIRST_RUN_WORDS = "tell me a few things"


class Journey:
    def __init__(self, root: Path) -> None:
        self.root, self.vault = root, root / "vault"
        self.checks: list[dict] = []
        self.env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8="1",
                        KNOWLEDGEOS_STATE_DIR=str(root / "state"))
        self.env.pop("KNOWLEDGEOS_VAULT", None)

    def check(self, name: str, passed: bool, detail: object = "") -> None:
        self.checks.append({"check": name, "passed": bool(passed), "detail": str(detail)[:400]})
        print(f"{'PASS' if passed else 'FAIL'} {name}" + ("" if passed else f": {str(detail)[:400]}"))

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-P", "-m", "knowledgeos", *args], capture_output=True,
                              text=True, env=self.env, cwd=str(self.root), stdin=subprocess.DEVNULL, timeout=300)

    def server(self) -> "Server":
        return Server(self)

    def drafts(self) -> list[str]:
        listed = self.cli("self", "pending", "--vault", str(self.vault)).stdout
        return [line.split()[0] for line in listed.splitlines() if line.startswith("People/")]


class Server:
    def __init__(self, journey: Journey) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-B", "-P", "-m", "knowledgeos", "mcp", "--vault", str(journey.vault),
             "--framing", "ndjson"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=journey.env, cwd=str(journey.root))
        self.sent = 0
        self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                "clientInfo": {"name": "first-day", "version": "0"}})

    def rpc(self, method: str, params: dict) -> dict:
        self.sent += 1
        message = {"jsonrpc": "2.0", "id": self.sent, "method": method, "params": params}
        self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def tool(self, name: str, **arguments) -> dict:
        reply = self.rpc("tools/call", {"name": name, "arguments": arguments})
        return json.loads(reply["result"]["content"][0]["text"])

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=30)


def offered(found: dict) -> list[str]:
    return [row["title"] for row in found.get("ranked", []) + found.get("possibly_related", [])]


def run(journey: Journey) -> None:
    check, cli, vault = journey.check, journey.cli, str(journey.vault)
    source = journey.root / "other-assistant.md"
    source.write_text(EXPORT, encoding="utf-8")

    made = cli("init", vault, "--name", "Asha", "--non-interactive")
    check("init makes a vault", made.returncode == 0 and (journey.vault / "People" / "Self.md").is_file(),
          made.stderr)
    profile = (journey.vault / "People" / "Self.md").read_bytes()

    def profile_unchanged(after: str) -> None:
        check(f"the profile is unchanged after {after}",
              (journey.vault / "People" / "Self.md").read_bytes() == profile)
    contract = (journey.vault / "AGENTS.md").read_text(encoding="utf-8")
    check("the starter contract holds no toolkit development text",
          "toolkit-dev" not in contract and "outputs/handoffs" not in contract)

    chat = journey.server()
    first = chat.tool("memory_session_start", task_hint="help me plan my week")
    check("the first chat asks the first-run question", FIRST_RUN_WORDS in (first.get("soft_prompt") or ""),
          first.get("soft_prompt"))
    check("the first chat carries the first-run steps", len(first.get("onboarding") or []) >= 3)
    starter = [row["path"] for row in first["context"]["relevant"].get("ranked", [])]
    check("no starter page is offered as memory", starter == [], starter)
    kept = chat.tool("memory_capture", content="I am training for the Pune half marathon in January.")
    check("a thought is kept without a title", kept.get("ok") is True, kept)
    again = chat.tool("memory_session_start", task_hint="next task")
    check("the first-run question is asked once", FIRST_RUN_WORDS not in (again.get("soft_prompt") or ""))
    chat.close()
    profile_unchanged("the first chat and a capture")

    dry = cli("import", str(source), "--vault", vault, "--label", "Other assistant", "--dry-run")
    check("a dry run writes nothing", dry.returncode == 0 and "nothing written" in dry.stdout
          and journey.drafts() == [], dry.stdout + dry.stderr)
    real = cli("import", str(source), "--vault", vault, "--label", "Other assistant")
    check("import keeps five facts and withholds the credential",
          real.returncode == 0 and "Imported 5." in real.stdout and "policy 1." in real.stdout, real.stdout)
    check("import names the next step", "twinaatma self review" in real.stdout)
    check("import never prints the credential", SECRET not in real.stdout + real.stderr)
    repeat = cli("import", str(source), "--vault", vault, "--label", "Other assistant")
    check("a second import adds nothing", "Imported 0. Already present 5." in repeat.stdout, repeat.stdout)
    check("a second import drafts no second profile change", len(journey.drafts()) == 1, journey.drafts())
    profile_unchanged("three imports")

    review = cli("self", "review", "--vault", vault)
    check("review refuses without a terminal", review.returncode == 2 and "terminal" in review.stderr,
          review.stderr)
    profile_unchanged("a review without a terminal")

    chat = journey.server()
    second = chat.tool("memory_session_start",
                       task_hint="choose between Postgres and MySQL for the new invoices service")
    context = second["context"]["relevant"].get("ranked", [])
    check("the next chat starts with the imported preference",
          any("Postgres over MongoDB" in (row.get("excerpt") or "") for row in context))
    check("an undecided draft is not offered as memory",
          not any(row["path"].startswith("People/Self-Proposals/") for row in context))
    exact = chat.tool("memory_search", query="half marathon")
    check("an exact search answers in ranked", bool(exact.get("ranked")) and "possibly_related" not in exact)
    plain = chat.tool("memory_search", query="when can I book a meeting")
    check("a plain question keeps ranked empty and offers the note as possibly related",
          plain.get("ranked") == [] and any("meetings before ten" in title for title in offered(plain)), plain)
    unknown = chat.tool("memory_search", query="zebra quokka xylophone")
    check("an unsupported question offers nothing", offered(unknown) == [], unknown)
    payloads = json.dumps([second, plain, chat.tool("memory_search", query="payments API key")])
    check("the credential is in no payload", SECRET not in payloads)
    refused = chat.tool("memory_accept_self_update", proposal_path=(journey.drafts() or ["none.md"])[0])
    check("an agent cannot approve the draft", refused.get("ok") is not True and "error" in refused, refused)
    chat.close()
    profile_unchanged("the second chat and a refused agent approval")
    held = [path.name for path in journey.vault.rglob("*.md")
            if SECRET in path.read_text(encoding="utf-8", errors="replace")]
    check("the credential is in no note", held == [], held)

    for host, opening in (("claude-code", "claude mcp add --scope user"), ("codex", "codex mcp add knowledgeos")):
        line = cli("setup-host", "--host", host, "--vault", vault, "--global", "--print")
        check(f"{host}: the user-level command is printed, not run",
              line.returncode == 0 and line.stdout.startswith(opening) and vault in line.stdout, line.stdout)
    wrote = cli("setup-host", "--host", "claude-code", "--vault", vault, "--write")
    check("claude-code: the project file is written",
          wrote.returncode == 0 and "knowledgeos" in json.loads(
              (journey.vault / ".mcp.json").read_text(encoding="utf-8")).get("mcpServers", {}), wrote.stderr)
    doctor = cli("doctor", "--vault", vault)
    check("doctor is healthy afterwards", doctor.returncode == 0, doctor.stdout[-400:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--output", type=Path, required=True, help="A new directory for the synthetic vault")
    args = parser.parse_args(argv)
    root = args.output.resolve()
    if root.exists():
        print(f"{root} exists; give a new directory.", file=sys.stderr)
        return 2
    root.mkdir(parents=True)
    journey = Journey(root)
    run(journey)
    failed = [row["check"] for row in journey.checks if not row["passed"]]
    (root / "report.json").write_text(json.dumps(
        {"checks": journey.checks, "failed": failed, "host_acceptance": "NOT CHECKED"}, indent=2) + "\n",
        encoding="utf-8")
    print(f"{len(journey.checks) - len(failed)} of {len(journey.checks)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
