"""A deliberately harmless MCP server: plain-text notes in one sandbox directory.

It exists so the trust-plane proxy has something real to front. Every tool
does exactly what its name says and nothing else; the only side effects are
files under ``NOTES_DIR`` (default: a temporary directory created at start).

Run it directly:  python -m notes_mcp_server
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def notes_dir() -> Path:
    raw = os.environ.get("NOTES_DIR")
    path = Path(raw) if raw else Path(tempfile.mkdtemp(prefix="atp-notes-"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(root: Path, note_id: str) -> Path:
    if not _ID.match(note_id):
        raise ValueError("note id must match [A-Za-z0-9._-]{1,64}")
    return root / f"{note_id}.txt"


def build_server(root: Path | None = None) -> MCPServer:
    root = root or notes_dir()
    server = MCPServer("notes", instructions="Plain-text notes stored in a sandbox directory.")

    @server.tool(
        name="list_notes",
        description="List the ids of all notes.",
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def list_notes() -> list[str]:
        return sorted(p.stem for p in root.glob("*.txt"))

    @server.tool(
        name="read_note",
        description="Return the text of a note.",
        annotations=ToolAnnotations(read_only_hint=True),
    )
    def read_note(id: str) -> str:
        p = _path(root, id)
        if not p.exists():
            raise FileNotFoundError(f"no note {id}")
        return p.read_text(encoding="utf-8")

    @server.tool(name="write_note", description="Create or overwrite a note.")
    def write_note(id: str, text: str) -> str:
        p = _path(root, id)
        p.write_text(text, encoding="utf-8")
        return f"wrote {id} ({len(text)} chars)"

    @server.tool(
        name="delete_note",
        description="Delete a note permanently.",
        annotations=ToolAnnotations(destructive_hint=True),
    )
    def delete_note(id: str) -> str:
        p = _path(root, id)
        if not p.exists():
            raise FileNotFoundError(f"no note {id}")
        p.unlink()
        return f"deleted {id}"

    return server


def main() -> None:
    build_server().run(transport="stdio")
