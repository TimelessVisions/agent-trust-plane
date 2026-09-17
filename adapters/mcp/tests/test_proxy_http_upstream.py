"""The proxy in front of a Streamable HTTP upstream: notes server served over
HTTP by uvicorn in a thread, proxy launched as a subprocess (stdio to us,
HTTP to the upstream, HTTP to the gateway). Same decisions, same evidence
as the stdio path; the transport is recorded on the trace."""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
import uvicorn
import yaml
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client

from atp_adapter_http import TrustPlaneClient
from atp_gateway.local import LocalGateway
from notes_mcp_server import build_server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def http_notes(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    notes = tmp_path / "notes"
    notes.mkdir()
    port = _free_port()
    app = build_server(notes).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("notes HTTP server did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/mcp", notes
    server.should_exit = True
    thread.join(timeout=10)


def _seed(operator: TrustPlaneClient) -> tuple[str, str]:
    from datetime import timedelta

    from atp_core import utcnow

    now = utcnow()
    human = {"id": "alice", "kind": "human"}
    agent = {"id": "notes-assistant", "kind": "agent"}
    token = operator.issue_credential(agent, label="http-e2e")["token"]
    root = operator.issue_delegation(
        {
            "label": "root",
            "grantor": human,
            "grantee": human,
            "capabilities": ["notes:read", "notes:write"],
            "resource_scope": ["id:*", "tool:*"],
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }
    )["grant_id"]
    grant = operator.issue_delegation(
        {
            "label": "assistant",
            "grantor": human,
            "grantee": agent,
            "parent_grant_id": root,
            "capabilities": ["notes:read", "notes:write"],
            "resource_scope": ["id:*", "tool:*"],
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )["grant_id"]
    return token, grant


def _mapping(name: str, cap: str, template: str) -> dict[str, str]:
    return {
        "mcp_tool": name,
        "tool": "mcp.notes",
        "action": name,
        "capability": cap,
        "resource_template": template,
    }


async def _session(config_path: Path, token: str) -> dict[str, Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atp_adapter_mcp", "--config", str(config_path), "--log-level", "warning"],
        env={**get_default_environment(), "ATP_AGENT_TOKEN": token},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = sorted(t.name for t in (await s.list_tools()).tools)
        write = await s.call_tool("write_note", {"id": "todo", "text": "over http"})
        read = await s.call_tool("read_note", {"id": "todo"})
        delete = await s.call_tool("delete_note", {"id": "todo"})
        return {"tools": tools, "write": write, "read": read, "delete": delete}


def _text(r: types.CallToolResult) -> str:
    return "".join(c.text for c in r.content if isinstance(c, types.TextContent))


def test_http_upstream_is_authorized_like_stdio(
    http_notes: tuple[str, Path], tmp_path: Path
) -> None:
    url, notes = http_notes
    with LocalGateway() as gw:
        operator = TrustPlaneClient(gw.url, operator_key=gw.operator_key)
        token, grant = _seed(operator)
        cfg = {
            "gateway": gw.url,
            "server_name": "notes",
            "principal": {"id": "alice", "kind": "human"},
            "agent": {"id": "notes-assistant", "kind": "agent"},
            "delegation_grant_id": grant,
            "upstream": {"url": url},
            "tools": [
                _mapping("write_note", "notes:write", "id:{id}"),
                _mapping("read_note", "notes:read", "id:{id}"),
                _mapping("delete_note", "notes:destroy", "id:{id}"),
            ],
        }
        path = tmp_path / "atp-mcp.yaml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        out = anyio.run(_session, path, token)

        assert out["tools"] == ["delete_note", "read_note", "write_note"]
        assert not out["write"].is_error and (notes / "todo.txt").exists()
        assert "over http" in _text(out["read"])
        assert out["delete"].is_error
        assert out["delete"].structured_content["reason_code"] == "CAPABILITY_NOT_GRANTED"
        assert (notes / "todo.txt").exists()

        traces = operator.list_traces(10)
        assert len(traces) == 3
        for summary in traces:
            trace = operator.get_trace(summary["trace_id"])
            desc = trace["envelope"]["provenance"]["task_description"]
            assert "atp-proxy (http" in desc, desc
            assert trace["integrity"]["valid"]
        completed = [t for t in traces if t["last_event_type"] == "execution_completed"]
        assert len(completed) == 2


def test_http_upstream_requires_https_off_localhost() -> None:
    from atp_adapter_mcp import UpstreamConfig

    with pytest.raises(ValueError):
        UpstreamConfig(url="http://10.0.0.5/mcp")
