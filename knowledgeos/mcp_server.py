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

MAX_FRAME_BYTES = 32 * 1024 * 1024


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _vault_from_env() -> Path:
    from knowledgeos.vault_resolve import resolve_vault

    return resolve_vault()


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
            from knowledgeos import __version__
            from knowledgeos.autopilot import AGENT_INSTRUCTIONS_COMPACT

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "knowledgeos-memory",
                        "version": __version__,
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
                # A protocol-level failure is any result that reports one, not only one
                # whose top-level key is literally `error`: refusals also arrive as
                # `{"ok": False, ...}` and `{"missing": [...]}`, and a strict client that
                # trusts `isError` treated those as success.
                is_error = isinstance(result, dict) and (
                    "error" in result
                    or result.get("ok") is False
                    or bool(result.get("missing"))
                    or bool(result.get("failed"))
                )
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
    _log(f"TwinAatma MCP Memory server ready. vault={vault}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _log(f"invalid json: {e}")
            continue
        if not isinstance(msg, dict):
            _log("unsupported message: JSON-RPC batches are not supported")
            continue
        try:
            resp = server.handle(msg)
        except Exception as e:
            _log(f"handler error: {e}")
            if msg.get("id") is None:
                continue
            resp = {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {"code": -32603, "message": str(e)},
            }
        if resp is not None:
            sys.stdout.write(json.dumps(resp, default=str) + "\n")
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
                key = key.strip().lower()
                if key == "content-length" and key in headers:
                    _log("duplicate Content-Length header; closing connection")
                    return
                headers[key] = val.strip()
            except ValueError:
                continue
        length = 0
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            # Without a usable length the stream is out of sync: we cannot know where
            # the next frame starts, so continuing would parse header bytes as JSON.
            _log("missing or invalid Content-Length; closing connection")
            return
        if length > MAX_FRAME_BYTES:
            _log(f"frame of {length} bytes exceeds limit; closing connection")
            return
        body = stdin.read(length)
        if not body or len(body) < length:
            return
        try:
            msg = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            _log(f"invalid json body: {e}")
            continue
        if not isinstance(msg, dict):
            _log("unsupported message: JSON-RPC batches are not supported")
            continue
        try:
            resp = server.handle(msg)
        except Exception as e:
            _log(f"handler error: {e}")
            if msg.get("id") is None:
                continue
            resp = {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {"code": -32603, "message": str(e)},
            }
        if resp is None:
            continue
        payload = json.dumps(resp).encode("utf-8")
        sys.stdout.buffer.write(
            f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        )
        sys.stdout.buffer.flush()


def run_stdio_auto(vault: Path | None = None) -> None:
    """MCP over stdio, accepting newline-delimited JSON or Content-Length frames.

    Each reply uses the framing of the request it answers, so either host convention works.
    """
    vault = vault or _vault_from_env()
    server = MCPServer(vault)
    _log(f"KnowledgeOS MCP Memory server ready (auto framing). vault={vault}")

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        try:
            line = stdin.readline()
        except (OSError, ValueError) as exc:
            _log(f"stdin error: {exc}")
            return
        if not line:
            return
        stripped = line.strip()
        if not stripped:
            continue
        framed = stripped.lower().startswith(b"content-length:")
        if framed:
            try:
                length = int(stripped.split(b":", 1)[1].strip())
            except (ValueError, IndexError):
                # Header line is malformed, so the body boundary is unknown too.
                _log("invalid Content-Length header; closing connection")
                return
            if length <= 0 or length > MAX_FRAME_BYTES:
                # A frame we refuse to read leaves the stream desynchronised; the
                # body would be reinterpreted as headers. Closing is the only
                # honest recovery, and the host will restart us.
                _log(f"refusing frame of {length} bytes; closing connection")
                return
            while True:
                header = stdin.readline()
                if not header:
                    return
                if header in (b"\r\n", b"\n"):
                    break
                if header.strip().lower().startswith(b"content-length:"):
                    _log("duplicate Content-Length header; closing connection")
                    return
            try:
                body = stdin.read(length)
            except (OSError, ValueError) as exc:
                _log(f"stdin error: {exc}")
                return
        else:
            body = stripped
        try:
            msg = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            _log(f"invalid json: {exc}")
            continue
        if not isinstance(msg, dict):
            _log("unsupported message: JSON-RPC batches are not supported")
            continue
        try:
            resp = server.handle(msg)
        except Exception as exc:
            _log(f"handler error: {exc}")
            if msg.get("id") is None:
                continue
            resp = {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {"code": -32603, "message": str(exc)},
            }
        if resp is None:
            continue
        payload = json.dumps(resp, default=str).encode("utf-8")
        try:
            if framed:
                stdout.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
            else:
                stdout.write(payload + b"\n")
            stdout.flush()
        except (OSError, ValueError) as exc:
            # The host closed the pipe; nothing left to talk to.
            _log(f"stdout closed: {exc}")
            return


if __name__ == "__main__":
    mode = os.environ.get("KNOWLEDGEOS_MCP_FRAMING", "auto")
    if mode == "ndjson":
        run_stdio()
    elif mode == "content-length":
        run_stdio_content_length()
    else:
        run_stdio_auto()
