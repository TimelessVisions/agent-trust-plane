"""End-to-end MCP proxy tests over the real protocol.

Topology under test (three processes, two protocols):

    this test (MCP client) ──stdio──▶ proxy subprocess ──HTTP──▶ gateway (thread, real port)
                                       └──stdio──▶ notes MCP server subprocess

Nothing is mocked. The notes server writes real files in a temp directory,
which is how "executed" and "blocked" are verified.
"""

from __future__ import annotations

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

AGENT = {"id": "notes-assistant", "kind": "agent"}
HUMAN = {"id": "alice", "kind": "human"}


@pytest.fixture(scope="module")
def gateway() -> Iterator[LocalGateway]:
    with LocalGateway() as gw:
        yield gw


@pytest.fixture
def operator(gateway: LocalGateway) -> TrustPlaneClient:
    return TrustPlaneClient(gateway.url, operator_key=gateway.operator_key)


def _seed(operator: TrustPlaneClient, *, scope: list[str]) -> tuple[str, str]:
    """Human -> notes-assistant with notes:read + notes:write over ``scope``."""
    token = operator.issue_credential(AGENT, label="proxy-test")["token"]
    now = datetime.now(UTC)
    root = operator.issue_delegation(
        {
            "label": "alice's notes",
            "grantor": HUMAN,
            "grantee": HUMAN,
            "capabilities": ["notes:read", "notes:write", "notes:delete"],
            "resource_scope": ["note:*"],
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }
    )["grant_id"]
    grant = operator.issue_delegation(
        {
            "label": "assistant: read/write notes, never delete",
            "grantor": HUMAN,
            "grantee": AGENT,
            "parent_grant_id": root,
            "capabilities": ["notes:read", "notes:write"],
            "resource_scope": scope,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )["grant_id"]
    return token, grant


def _write_config(path: Path, gateway_url: str, grant_id: str, notes_dir: Path) -> None:
    cfg: dict[str, Any] = {
        "gateway": gateway_url,
        "server_name": "notes",
        "principal": HUMAN,
        "agent": AGENT,
        "delegation_grant_id": grant_id,
        "agent_token_env": "ATP_AGENT_TOKEN",
        "upstream": {
            "command": sys.executable,
            "args": ["-m", "notes_mcp_server"],
            "env": {"NOTES_DIR": str(notes_dir)},
        },
        "tools": [
            {
                "mcp_tool": "write_note",
                "tool": "mcp.notes",
                "action": "write_note",
                "capability": "notes:write",
                "resource_template": "note:{id}",
                "resource_arguments": ["id"],
            },
            {
                "mcp_tool": "read_note",
                "tool": "mcp.notes",
                "action": "read_note",
                "capability": "notes:read",
                "resource_template": "note:{id}",
                "resource_arguments": ["id"],
            },
            {
                "mcp_tool": "list_notes",
                "tool": "mcp.notes",
                "action": "list_notes",
                "capability": "notes:read",
                "resource_template": "note:*",
            },
        ],
    }
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")


class _ProxySession:
    """Async context manager yielding an MCP ClientSession to the proxy subprocess."""

    def __init__(self, config_path: Path, token: str) -> None:
        self.params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "atp_adapter_mcp", "--config", str(config_path), "--log-level", "warning"],
            env={**get_default_environment(), "ATP_AGENT_TOKEN": token},
        )

    async def __aenter__(self) -> ClientSession:
        self._cm = stdio_client(self.params)
        read, write = await self._cm.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        return self._session

    async def __aexit__(self, *exc: object) -> None:
        await self._session.__aexit__(None, None, None)
        await self._cm.__aexit__(None, None, None)


def _text(result: types.CallToolResult) -> str:
    return "".join(c.text for c in result.content if isinstance(c, types.TextContent))


async def _run(config_path: Path, token: str, body: Any) -> Any:
    async with _ProxySession(config_path, token) as session:
        return await body(session)


def test_proxy_forwards_allowed_calls_and_blocks_unmapped_ones(
    gateway: LocalGateway, operator: TrustPlaneClient, tmp_path: Path
) -> None:
    token, grant = _seed(operator, scope=["note:*"])
    notes_dir = tmp_path / "notes"
    cfg = tmp_path / "atp-mcp.yaml"
    _write_config(cfg, gateway.url, grant, notes_dir)

    async def body(session: ClientSession) -> dict[str, Any]:
        listed = await session.list_tools()
        write = await session.call_tool("write_note", {"id": "todo", "text": "buy milk"})
        read = await session.call_tool("read_note", {"id": "todo"})
        delete = await session.call_tool("delete_note", {"id": "todo"})
        return {
            "tools": sorted(t.name for t in listed.tools),
            "write": write,
            "read": read,
            "delete": delete,
        }

    out = anyio.run(_run, cfg, token, body)

    # tools/list: unmapped delete_note is hidden from the model by default
    assert out["tools"] == ["list_notes", "read_note", "write_note"]

    # allowed call: forwarded, upstream response preserved, real side effect
    assert out["write"].is_error is False
    assert _text(out["write"]) == "wrote todo (8 chars)"
    assert (notes_dir / "todo.txt").read_text(encoding="utf-8") == "buy milk"
    assert _text(out["read"]) == "buy milk"

    # unmapped call: denied by the gateway (capability not delegated), file untouched
    assert out["delete"].is_error is True
    denial = out["delete"].structured_content
    assert denial["reason_code"] == "CAPABILITY_NOT_GRANTED"
    assert (notes_dir / "todo.txt").exists()

    # evidence: the allowed call's trace shows release + reported outcome
    trace = operator.get_trace(_trace_id_of(operator, "write_note"))
    types_seen = [e["event_type"] for e in trace["events"]]
    assert types_seen == [
        "action_proposed",
        "delegation_resolved",
        "policy_evaluated",
        "decision_made",
        "grant_issued",
        "execution_attempted",
        "execution_released",
        "execution_completed",
    ]
    completed = trace["events"][-1]
    assert completed["actor"] == "notes-assistant"
    assert completed["payload"]["reported_by"] == "external_executor"
    assert completed["payload"]["summary"]["text_preview"] == "wrote todo (8 chars)"
    assert trace["integrity"]["valid"]
    assert token not in str(trace)

    # evidence: the denied call is on the record too
    denied = operator.get_trace(denial["trace_id"])
    assert denied["decision"]["outcome"] == "DENY"
    assert denied["envelope"]["capability"] == "mcp:unmapped"
    assert denied["envelope"]["action"] == "delete_note"


def test_proxy_enforces_argument_derived_resource_scope(
    gateway: LocalGateway, operator: TrustPlaneClient, tmp_path: Path
) -> None:
    """The delegation only covers note:shared. Writing note:secret is a
    mapped tool with a permitted name — it is the *argument* that is denied."""
    token, grant = _seed(operator, scope=["note:shared"])
    notes_dir = tmp_path / "notes"
    cfg = tmp_path / "atp-mcp.yaml"
    _write_config(cfg, gateway.url, grant, notes_dir)

    async def body(session: ClientSession) -> dict[str, Any]:
        ok = await session.call_tool("write_note", {"id": "shared", "text": "fine"})
        bad = await session.call_tool("write_note", {"id": "secret", "text": "exfil"})
        return {"ok": ok, "bad": bad}

    out = anyio.run(_run, cfg, token, body)
    assert out["ok"].is_error is False
    assert (notes_dir / "shared.txt").exists()
    assert out["bad"].is_error is True
    assert out["bad"].structured_content["reason_code"] == "RESOURCE_OUT_OF_SCOPE"
    assert not (notes_dir / "secret.txt").exists()


def test_proxy_with_revoked_credential_cannot_call_anything(
    gateway: LocalGateway, operator: TrustPlaneClient, tmp_path: Path
) -> None:
    token, grant = _seed(operator, scope=["note:*"])
    notes_dir = tmp_path / "notes"
    cfg = tmp_path / "atp-mcp.yaml"
    _write_config(cfg, gateway.url, grant, notes_dir)
    # revoke the credential the proxy will use
    for c in operator.list_credentials(AGENT["id"]):
        if c["revoked_at"] is None:
            operator.revoke_credential(c["credential_id"])

    async def body(session: ClientSession) -> types.CallToolResult:
        return await session.call_tool("write_note", {"id": "x", "text": "y"})

    result = anyio.run(_run, cfg, token, body)
    assert result.is_error is True
    assert result.structured_content["reason_code"] == "AGENT_CREDENTIAL_REVOKED"
    assert not (notes_dir / "x.txt").exists()


def test_direct_upstream_access_is_not_protected(tmp_path: Path) -> None:
    """Documented limitation: a client that launches the upstream itself
    bypasses everything. The proxy is the enforcement point."""
    notes_dir = tmp_path / "notes"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "notes_mcp_server"],
        env={**get_default_environment(), "NOTES_DIR": str(notes_dir)},
    )

    async def body() -> None:
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await s.call_tool("write_note", {"id": "direct", "text": "no gateway involved"})

    anyio.run(body)
    assert (notes_dir / "direct.txt").exists()


def _trace_id_of(operator: TrustPlaneClient, action: str) -> str:
    for summary in operator.list_traces(50):
        trace = operator.get_trace(summary["trace_id"])
        env = trace.get("envelope")
        if env and env["action"] == action and trace["decision"]["outcome"] == "ALLOW":
            return str(summary["trace_id"])
    raise AssertionError(f"no ALLOW trace for {action}")
