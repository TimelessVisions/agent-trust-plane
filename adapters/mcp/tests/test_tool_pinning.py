"""E1: tool-definition pinning, including tools/list_changed revalidation.

The pin covers the canonical name, description and inputSchema. Pinned mismatches
must fail closed before gateway authorization or reaching the upstream process.
"""

from __future__ import annotations

from typing import Any

import anyio
from mcp import types

from atp_adapter_mcp.config import ProxyConfig, UpstreamConfig
from atp_adapter_mcp.discovery import propose_config
from atp_adapter_mcp.mapping import ToolMapping, tool_definition_sha256
from atp_adapter_mcp.proxy import TrustPlaneProxy, Upstream


def _tool(description: str = "Writes notes", *, tool_name: str = "write_note") -> types.Tool:
    return types.Tool(
        name=tool_name,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
            "required": ["id", "text"],
        },
    )


class _MutableSession:
    def __init__(self, tool: types.Tool) -> None:
        self.tools = [tool]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> types.ListToolsResult:
        return types.ListToolsResult(tools=list(self.tools))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        self.calls.append((name, arguments))
        return types.CallToolResult(content=[])


class _UnexpectedGateway:
    def authorize(self, _envelope: object) -> None:
        raise AssertionError("tool definition failed before gateway authorization")


def _proxy(tool: types.Tool, pin: str | None) -> tuple[TrustPlaneProxy, _MutableSession]:
    config = ProxyConfig(
        server_name="notes",
        upstream=UpstreamConfig(command="unused"),
        tools=(
            ToolMapping(
                mcp_tool="write_note",
                tool="mcp.notes",
                action="write_note",
                capability="notes:write",
                resource_template="note:{id}",
                schema_sha256=pin,
            ),
        ),
    )
    session = _MutableSession(tool)
    upstream = Upstream(
        session=session,  # type: ignore[arg-type]
        tools=[tool],
        transport="stdio",
        protocol_version="2025-11-25",
        tool_list_state={"dirty": False},
    )
    return TrustPlaneProxy(config, _UnexpectedGateway(), upstream), session  # type: ignore[arg-type]


def test_definition_change_denied_with_pin() -> None:
    original = _tool()
    proxy, session = _proxy(original, tool_definition_sha256(original))

    async def run() -> tuple[types.ListToolsResult, types.ListToolsResult, types.CallToolResult]:
        before = await proxy._list_tools(None, None)  # type: ignore[arg-type]
        session.tools = [_tool("The description has been replaced by an attacker")]
        assert proxy.upstream.tool_list_state is not None
        proxy.upstream.tool_list_state["dirty"] = True  # tools/list_changed notification
        after = await proxy._list_tools(None, None)  # type: ignore[arg-type]
        denied = await proxy._call_tool(  # type: ignore[arg-type]
            None, types.CallToolRequestParams(name="write_note", arguments={"id": "memo"})
        )
        return before, after, denied

    before, after, denied = anyio.run(run)
    assert [t.name for t in before.tools] == ["write_note"]
    assert after.tools == []
    assert denied.is_error
    assert denied.structured_content is not None
    assert denied.structured_content["reason_code"] == "TOOL_DEFINITION_CHANGED"
    assert session.calls == []


def test_init_writes_schema_pin() -> None:
    original = _tool()
    proposal = propose_config(
        "notes", UpstreamConfig(command="ignored"), [original], casefold=False
    )
    mapping = proposal.config.mapping_for("write_note")
    assert mapping is not None
    assert mapping.schema_sha256 == tool_definition_sha256(original)
    assert len(mapping.schema_sha256) == 64


def test_unpinned_config_keeps_current_behaviour() -> None:
    proxy, session = _proxy(_tool(), None)

    async def run() -> types.ListToolsResult:
        session.tools = [_tool("Changed description")]
        assert proxy.upstream.tool_list_state is not None
        proxy.upstream.tool_list_state["dirty"] = True
        return await proxy._list_tools(None, None)  # type: ignore[arg-type]

    assert [t.name for t in anyio.run(run).tools] == ["write_note"]


def test_tool_schema_pin_canonical_three_field_payload() -> None:
    tool = _tool()
    digest = tool_definition_sha256(tool)
    reordered = types.Tool(
        name="write_note",
        description="Writes notes",
        input_schema={
            "required": ["id", "text"],
            "properties": {"text": {"type": "string"}, "id": {"type": "string"}},
            "type": "object",
        },
    )
    assert digest == tool_definition_sha256(reordered)
    assert digest != tool_definition_sha256(_tool("Different description"))
    assert digest != tool_definition_sha256(_tool(tool_name="other_name"))
    changed_schema = _tool().model_copy(
        update={"input_schema": {"type": "object", "properties": {"id": {"type": "integer"}}}}
    )
    assert digest != tool_definition_sha256(changed_schema)


def test_changed_tool_denied_even_without_list_changed_notification() -> None:
    original = _tool()
    proxy, session = _proxy(original, tool_definition_sha256(original))
    session.tools = [_tool("Adversarial changed description")]
    # No tools/list_changed notification was sent, so the cached discovery
    # entry still looks safe; each pinned execution must re-list anyway.
    assert proxy.upstream.tool_list_state == {"dirty": False}

    async def call() -> types.CallToolResult:
        return await proxy._call_tool(  # type: ignore[arg-type]
            None, types.CallToolRequestParams(name="write_note", arguments={"id": "memo"})
        )

    denied = anyio.run(call)
    assert denied.structured_content is not None
    assert denied.structured_content["reason_code"] == "TOOL_DEFINITION_CHANGED"
    assert session.calls == []


def test_unverifiable_pinned_definition_cannot_execute() -> None:
    original = _tool()
    proxy, session = _proxy(original, tool_definition_sha256(original))

    async def broken_list() -> types.ListToolsResult:
        raise ConnectionError("upstream list failed")

    session.list_tools = broken_list  # type: ignore[method-assign]

    async def call() -> types.CallToolResult:
        return await proxy._call_tool(  # type: ignore[arg-type]
            None, types.CallToolRequestParams(name="write_note", arguments={"id": "memo"})
        )

    refused = anyio.run(call)
    assert refused.structured_content is not None
    assert refused.structured_content["reason_code"] == "UPSTREAM_ERROR"
    assert session.calls == []
