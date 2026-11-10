"""REQUIRE_APPROVAL through the real MCP proxy: the denial names the trace and
`atp approve <trace>`; after approval the identical call runs exactly once."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession
from test_proxy_e2e import HUMAN, _run, _seed, _text, _write_config

from atp_gateway import GatewaySettings
from atp_gateway.local import LocalGateway

POLICIES = """\
version: 1
policy_sets:
  - version: notes-approval
    description: writes need an editor
    rules:
      - id: writes-need-editor
        applies_to: {tool: mcp.notes, action: write_note}
        kind: require_approval
        approver_role: editor
"""


def test_proxy_require_approval_then_approve_then_retry(tmp_path: Path) -> None:
    policy = tmp_path / "policies.yaml"
    policy.write_text(POLICIES, encoding="utf-8")
    settings = GatewaySettings(
        _env_file=None,  # type: ignore[call-arg]
        database_path=":memory:",
        policy_file=str(policy),
        default_policy_set="notes-approval",
        approver_roles=f"{HUMAN['kind']}:{HUMAN['id']}=editor",
    )
    with LocalGateway(settings) as gateway:
        operator = gateway.operator_client()
        token, grant = _seed(operator, scope=["note:*"])
        notes_dir = tmp_path / "notes"
        cfg = tmp_path / "atp-mcp.yaml"
        _write_config(cfg, gateway.url, grant, notes_dir)
        args = {"id": "memo", "text": "pay rent"}

        async def body(session: ClientSession) -> dict[str, Any]:
            first = await session.call_tool("write_note", args)
            trace_id = first.structured_content["trace_id"]  # type: ignore[index]
            await anyio.to_thread.run_sync(
                lambda: operator.approve(trace_id, HUMAN, expires_in="5m")
            )
            second = await session.call_tool("write_note", args)
            third = await session.call_tool("write_note", args)
            return {"first": first, "second": second, "third": third, "trace": trace_id}

        out = anyio.run(_run, cfg, token, body)

    first = out["first"]
    assert first.is_error is True
    denial = first.structured_content
    assert denial["outcome"] == "REQUIRE_APPROVAL"
    trace = out["trace"]
    assert f"atp approve {trace}" in _text(first)
    assert trace in denial["message"]

    assert out["second"].is_error is False
    assert _text(out["second"]) == "wrote memo (8 chars)"
    assert (notes_dir / "memo.txt").read_text(encoding="utf-8") == "pay rent"

    # The approval was for one execution; a new call asks again on a new trace.
    assert out["third"].is_error is True
    assert out["third"].structured_content["outcome"] == "REQUIRE_APPROVAL"
    assert out["third"].structured_content["trace_id"] != trace
