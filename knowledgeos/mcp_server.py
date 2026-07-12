"""Minimal stdlib MCP server (JSON-RPC over stdio) for KnowledgeOS Memory API.

No pip dependencies. Compatible with Cursor / Claude Desktop style MCP hosts.

Logging MUST go to stderr — stdout is the protocol stream.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from knowledgeos.memory import TOOL_SPECS, MemoryAPI, dispatch


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _vault_from_env() -> Path:
    env = os.environ.get("KNOWLEDGEOS_VAULT")
    if env:
        return Path(env).resolve()
    # Default: package parent (toolkit / vault root)
    return Path(__file__).resolve().parent.parent


class MCPServer:
    def __init__(self, vault: Path):
        self.api = MemoryAPI(vault)
        self.vault = vault

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        # Notifications have no id
        if method == "notifications/initialized":
            return None
        if method == "notifications/cancelled":
            return None

        if method == "initialize":
            from knowledgeos.autopilot import AGENT_INSTRUCTIONS_COMPACT

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "knowledgeos-memory",
                        "version": "0.4.0-dev",
                    },
                    "instructions": AGENT_INSTRUCTIONS_COMPACT,
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOL_SPECS},
            }

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                result = dispatch(self.api, name, arguments)
                payload = json.dumps(result, indent=2, default=str)
                is_error = isinstance(result, dict) and "error" in result
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": payload}],
                        "isError": bool(is_error),
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                        "isError": True,
                    },
                }

        # Unknown method
        if msg_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def run_stdio(vault: Path | None = None) -> None:
    vault = vault or _vault_from_env()
    server = MCPServer(vault)
    _log(f"KnowledgeOS MCP Memory server ready. vault={vault}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _log(f"invalid json: {e}")
            continue
        # Support Content-Length framed messages if a host sends them as single-line JSON still;
        # Cursor typically uses newline-delimited or Content-Length. Handle both simply:
        resp = server.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def run_stdio_content_length(vault: Path | None = None) -> None:
    """MCP stdio with Content-Length framing (common for desktop hosts)."""
    vault = vault or _vault_from_env()
    server = MCPServer(vault)
    _log(f"KnowledgeOS MCP Memory server ready (Content-Length). vault={vault}")

    stdin = sys.stdin.buffer
    while True:
        headers: dict[str, str] = {}
        while True:
            line = stdin.readline()
            if not line:
                return
            if line in (b"\r\n", b"\n"):
                break
            try:
                key, val = line.decode("utf-8").split(":", 1)
                headers[key.strip().lower()] = val.strip()
            except ValueError:
                continue
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            continue
        body = stdin.read(length)
        if not body:
            return
        try:
            msg = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            _log(f"invalid json body: {e}")
            continue
        resp = server.handle(msg)
        if resp is None:
            continue
        payload = json.dumps(resp).encode("utf-8")
        sys.stdout.buffer.write(
            f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        )
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    mode = os.environ.get("KNOWLEDGEOS_MCP_FRAMING", "content-length")
    if mode == "ndjson":
        run_stdio()
    else:
        run_stdio_content_length()
