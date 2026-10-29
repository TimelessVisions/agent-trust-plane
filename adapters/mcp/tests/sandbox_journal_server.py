"""Sandbox MCP server that records every tool invocation before any side effect.

The proxy tests launch this process (stdio) or call ``build_server`` over
Streamable HTTP. A denied call is proven by the absence of its name in the
journal, which is appended and flushed inside the tool, before the note
file changes. This is the upstream server, not a stand-in for the proxy.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

_ID_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


def _note_path(root: Path, note_id: str) -> Path:
    if not note_id or len(note_id) > 64 or any(ch not in _ID_OK for ch in note_id):
        raise ValueError("note id must match [A-Za-z0-9._-]{1,64}")
    return root / f"{note_id}.txt"


def _record(journal: Path, tool: str) -> None:
    """Append ``tool`` and flush before the caller is allowed to touch a file."""
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(tool + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def build_server(root: Path, journal: Path) -> MCPServer:
    root.mkdir(parents=True, exist_ok=True)
    server = MCPServer(
        "sandbox-journal",
        instructions="Sandbox notes. Every tool records its name before it runs.",
    )

    @server.tool(name="write_note", description="Create or overwrite a note.")
    def write_note(id: str, text: str) -> str:
        _record(journal, "write_note")
        path = _note_path(root, id)
        path.write_text(text, encoding="utf-8")
        return f"wrote {id} ({len(text)} chars)"

    @server.tool(
        name="delete_note",
        description="Delete a note permanently.",
        annotations=ToolAnnotations(destructive_hint=True),
    )
    def delete_note(id: str) -> str:
        _record(journal, "delete_note")
        path = _note_path(root, id)
        if not path.exists():
            raise FileNotFoundError(f"no note {id}")
        path.unlink()
        return f"deleted {id}"

    return server


def journal_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _serve_http(root: Path, journal: Path, endpoint: str, ready: Path | None) -> None:
    host, port_text = endpoint.rsplit(":", 1)
    app = build_server(root, journal).streamable_http_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=int(port_text), log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("sandbox HTTP server did not start")
        time.sleep(0.02)
    if ready is not None:
        ready.write_text("ready\n", encoding="utf-8")
    thread.join()


def main() -> None:
    root = Path(os.environ["ATP_SANDBOX_ROOT"])
    journal = Path(os.environ["ATP_SANDBOX_JOURNAL"])
    http = os.environ.get("ATP_SANDBOX_HTTP")
    if http:
        ready_raw = os.environ.get("ATP_SANDBOX_READY")
        _serve_http(root, journal, http, Path(ready_raw) if ready_raw else None)
        return
    build_server(root, journal).run(transport="stdio")


if __name__ == "__main__":
    main()
