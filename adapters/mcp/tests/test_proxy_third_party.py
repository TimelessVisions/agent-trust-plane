"""Opt-in: proxy the reference ``@modelcontextprotocol/server-filesystem``.

Needs Node/npx and network for the first download, so it only runs when
``ATP_E2E_NPX=1``. It exists to keep the claim "verified against a
third-party MCP server" honest and re-checkable.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client

from atp_adapter_http import TrustPlaneClient
from atp_gateway.local import LocalGateway

pytestmark = pytest.mark.skipif(
    os.environ.get("ATP_E2E_NPX") != "1" or shutil.which("npx") is None,
    reason="set ATP_E2E_NPX=1 with npx on PATH to run the third-party server test",
)

AGENT = {"id": "fs-assistant", "kind": "agent"}
HUMAN = {"id": "alice", "kind": "human"}


@pytest.fixture(scope="module")
def gateway() -> Iterator[LocalGateway]:
    with LocalGateway() as gw:
        yield gw


def test_reference_filesystem_server_behind_proxy(gateway: LocalGateway, tmp_path: Path) -> None:
    operator = TrustPlaneClient(gateway.url, operator_key=gateway.operator_key)
    token = operator.issue_credential(AGENT, label="fs")["token"]
    now = datetime.now(UTC)
    root = operator.issue_delegation(
        {
            "label": "alice's sandbox",
            "grantor": HUMAN,
            "grantee": HUMAN,
            "capabilities": ["fs:read", "fs:write"],
            "resource_scope": ["fs:sandbox"],
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }
    )["grant_id"]
    grant = operator.issue_delegation(
        {
            "label": "assistant: read and write inside the sandbox",
            "grantor": HUMAN,
            "grantee": AGENT,
            "parent_grant_id": root,
            "capabilities": ["fs:read", "fs:write"],
            "resource_scope": ["fs:sandbox"],
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )["grant_id"]

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    npx = "npx.cmd" if os.name == "nt" else "npx"
    cfg: dict[str, Any] = {
        "gateway": gateway.url,
        "server_name": "filesystem",
        "principal": HUMAN,
        "agent": AGENT,
        "delegation_grant_id": grant,
        "upstream": {
            "command": npx,
            "args": ["-y", "@modelcontextprotocol/server-filesystem", str(sandbox)],
        },
        "tools": [
            {
                "mcp_tool": "write_file",
                "tool": "mcp.filesystem",
                "action": "write_file",
                "capability": "fs:write",
                "resource_template": "fs:sandbox",
            },
            {
                "mcp_tool": "list_directory",
                "tool": "mcp.filesystem",
                "action": "list_directory",
                "capability": "fs:read",
                "resource_template": "fs:sandbox",
            },
        ],
    }
    cfg_path = tmp_path / "atp-mcp.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atp_adapter_mcp", "--config", str(cfg_path), "--log-level", "warning"],
        env={**get_default_environment(), "ATP_AGENT_TOKEN": token},
    )

    async def body() -> dict[str, Any]:
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            target = str(sandbox / "hello.txt")
            write = await s.call_tool("write_file", {"path": target, "content": "hi"})
            listing = await s.call_tool("list_directory", {"path": str(sandbox)})
            move = await s.call_tool(
                "move_file", {"source": target, "destination": str(sandbox / "moved.txt")}
            )
            return {"tools": tools, "write": write, "listing": listing, "move": move}

    out = anyio.run(body)
    assert out["tools"] == ["list_directory", "write_file"]
    assert out["write"].is_error is False
    assert (sandbox / "hello.txt").read_text(encoding="utf-8") == "hi"
    assert "hello.txt" in "".join(
        c.text for c in out["listing"].content if isinstance(c, types.TextContent)
    )
    assert out["move"].is_error is True
    assert out["move"].structured_content["reason_code"] == "CAPABILITY_NOT_GRANTED"
    assert (sandbox / "hello.txt").exists() and not (sandbox / "moved.txt").exists()
