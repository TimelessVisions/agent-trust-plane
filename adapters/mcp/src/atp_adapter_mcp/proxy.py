"""The MCP proxy: a stdio MCP server that fronts one upstream stdio MCP server
and routes every ``tools/call`` through the trust gateway.

Wire path for one call:

    MCP client ──stdio──▶ proxy ──HTTP──▶ gateway  (authorize; on ALLOW: execute → released)
                          proxy ──stdio──▶ upstream MCP server (only after release)
                          proxy ──HTTP──▶ gateway  (report outcome against the consumed grant)
                          proxy ──stdio──▶ MCP client (upstream result, unchanged)

What this is: gateway-mediated enforcement for clients that reach the
upstream *through this proxy*. What it is not: protection against an agent
that can launch or reach the upstream server directly. See docs/mcp-proxy.md.

Protocol support: MCP Python SDK 2.x lowlevel server, stdio transport only,
``tools/list`` and ``tools/call``. Prompts and resources are not proxied.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import anyio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.server import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from atp_adapter_http import GatewayError, TrustPlaneClient
from atp_adapter_mcp.config import ProxyConfig
from atp_core import ActionEnvelope, Provenance, canonical_json, new_trace_id

log = logging.getLogger("atp.mcp-proxy")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._:-]")
UNMAPPED_CAPABILITY = "mcp:unmapped"


def _safe_action(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", name)[:64]
    return cleaned or "unnamed"


@dataclass
class Upstream:
    """A live session to the upstream MCP server."""

    session: ClientSession
    tools: list[types.Tool]

    def tool(self, name: str) -> types.Tool | None:
        return next((t for t in self.tools if t.name == name), None)


@contextlib.asynccontextmanager
async def connect_upstream(config: ProxyConfig) -> AsyncIterator[Upstream]:
    params = StdioServerParameters(
        command=config.upstream.command,
        args=list(config.upstream.args),
        env={**get_default_environment(), **config.upstream.env},
        cwd=config.upstream.cwd,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        yield Upstream(session=session, tools=list(listed.tools))


def _denied(payload: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=True,
    )


def _summarise(result: types.CallToolResult) -> dict[str, Any]:
    """A bounded, secret-free description of an upstream result for the trace."""
    kinds = [c.type for c in result.content]
    preview = ""
    for c in result.content:
        if isinstance(c, types.TextContent):
            preview = c.text[:200]
            break
    return {"is_error": bool(result.is_error), "content_types": kinds, "text_preview": preview}


class TrustPlaneProxy:
    def __init__(self, config: ProxyConfig, client: TrustPlaneClient, upstream: Upstream) -> None:
        self.config = config
        self.client = client
        self.upstream = upstream
        self.server: Server[Any] = Server(
            f"atp-proxy:{config.server_name}",
            version="0.2.0",
            instructions=(
                "Tool calls are authorized by Agent Trust Plane before execution. A denied "
                "call returns isError with a reason_code; do not retry it with different "
                "arguments unless the reason indicates a correctable input."
            ),
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )

    # ------------------------------------------------------------ tools/list
    async def _list_tools(
        self, _ctx: ServerRequestContext[Any], _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        tools = [
            t
            for t in self.upstream.tools
            if self.config.expose_unmapped_tools or self.config.mapping_for(t.name) is not None
        ]
        return types.ListToolsResult(tools=tools)

    # ------------------------------------------------------------ tools/call
    async def _call_tool(
        self, _ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        name = params.name
        arguments: dict[str, Any] = dict(params.arguments or {})
        if self.upstream.tool(name) is None:
            return _denied({"reason_code": "TOOL_UNKNOWN", "message": f"no such tool: {name}"})

        try:
            envelope = self._envelope_for(name, arguments)
        except ArgumentsTooLargeError as exc:
            return _denied({"reason_code": "TOOL_ARGUMENTS_TOO_LARGE", "message": str(exc)})
        if envelope is None:
            return _denied(
                {
                    "reason_code": "TOOL_ARGUMENTS_INVALID",
                    "message": "arguments do not identify the resource this tool needs",
                }
            )

        try:
            auth = await anyio.to_thread.run_sync(self.client.authorize, envelope)
        except GatewayError as exc:
            return _denied(
                {
                    "reason_code": exc.reason_code,
                    "message": exc.message,
                    "trace_id": envelope.trace_id,
                }
            )
        decision = auth.decision
        if auth.execution_grant is None:
            return _denied(
                {
                    "reason_code": decision.reason_code.value,
                    "outcome": decision.outcome.value,
                    "message": decision.explanation,
                    "matched_policy": (
                        decision.matched_policy.qualified if decision.matched_policy else None
                    ),
                    "trace_id": envelope.trace_id,
                }
            )

        try:
            release = await anyio.to_thread.run_sync(
                self.client.execute, envelope, auth.execution_grant
            )
        except GatewayError as exc:
            return _denied(
                {
                    "reason_code": exc.reason_code,
                    "message": exc.message,
                    "trace_id": envelope.trace_id,
                }
            )
        if release.status != "released":
            return _denied(
                {
                    "reason_code": release.reason_code.value,
                    "message": release.message,
                    "trace_id": envelope.trace_id,
                }
            )

        grant_id = auth.execution_grant.grant_id
        try:
            with anyio.fail_after(self.config.request_timeout_seconds):
                raw = await self.upstream.session.call_tool(name, arguments)
        except Exception as exc:
            error_text = str(exc)[:500]
            await anyio.to_thread.run_sync(
                lambda: self.client.report_outcome(
                    grant_id, succeeded=False, summary={"error": error_text}
                )
            )
            return _denied(
                {
                    "reason_code": "UPSTREAM_ERROR",
                    "message": str(exc)[:500],
                    "trace_id": envelope.trace_id,
                }
            )

        result: types.CallToolResult
        if isinstance(raw, types.CallToolResult) and raw.result_type == "complete":
            result = raw
        else:
            # input_required / task-style results are not proxied in this release.
            result = _denied(
                {"reason_code": "UPSTREAM_UNSUPPORTED_RESULT", "trace_id": envelope.trace_id}
            )
        summary = _summarise(result)
        with contextlib.suppress(GatewayError):
            await anyio.to_thread.run_sync(
                lambda: self.client.report_outcome(
                    grant_id, succeeded=not result.is_error, summary=summary
                )
            )
        return result

    # ------------------------------------------------------------- envelopes
    def _envelope_for(self, name: str, arguments: dict[str, Any]) -> ActionEnvelope | None:
        mapping = self.config.mapping_for(name)
        if mapping is None:
            # Unmapped: still send it, so the denial is on the record. The
            # capability 'mcp:unmapped' is never delegated in any sane setup.
            return ActionEnvelope(
                trace_id=new_trace_id(),
                principal=self.config.principal,
                agent=self.config.agent,
                delegation_grant_id=self.config.delegation_grant_id,
                capability=UNMAPPED_CAPABILITY,
                tool=self.config.envelope_tool,
                action=_safe_action(name),
                resource=f"tool:{_safe_action(name)}",
                arguments=_bounded(arguments),
                provenance=Provenance(agent_rationale="unmapped MCP tool"),
            )
        try:
            resource = mapping.resource_for(arguments)
        except ValueError:
            return None
        if _SAFE_NAME.search(resource) or len(resource) > 256:
            return None
        payload = {k: v for k, v in arguments.items() if k not in mapping.resource_arguments}
        return ActionEnvelope(
            trace_id=new_trace_id(),
            principal=self.config.principal,
            agent=self.config.agent,
            delegation_grant_id=self.config.delegation_grant_id,
            capability=mapping.capability,
            tool=self.config.envelope_tool,
            action=mapping.action,
            resource=resource,
            arguments=_bounded(payload),
            provenance=Provenance(model=None),
        )


MAX_ARGUMENT_BYTES = 15 * 1024


class ArgumentsTooLargeError(ValueError):
    pass


def _bounded(arguments: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on oversized arguments. The grant binds the exact argument
    hash, so the proxy must never authorize a truncated form and forward the
    original; it refuses instead."""
    if len(canonical_json(arguments)) > MAX_ARGUMENT_BYTES:
        raise ArgumentsTooLargeError("tool arguments exceed the authorizable size")
    return arguments


async def serve(config: ProxyConfig) -> None:
    client = TrustPlaneClient(config.gateway, agent_token=config.agent_token())
    async with connect_upstream(config) as upstream:
        proxy = TrustPlaneProxy(config, client, upstream)
        log.info(
            "proxying %s (%d tools, %d mapped) via %s",
            config.server_name,
            len(upstream.tools),
            sum(1 for t in upstream.tools if config.mapping_for(t.name)),
            config.gateway,
        )
        async with stdio_server() as (read, write):
            await proxy.server.run(read, write, proxy.server.create_initialization_options())


def main(argv: list[str] | None = None) -> None:
    import argparse

    from atp_adapter_mcp.config import load_config

    parser = argparse.ArgumentParser(prog="atp-mcp-proxy")
    parser.add_argument("--config", required=True, help="path to the proxy YAML config")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), stream=sys.stderr)
    anyio.run(serve, load_config(args.config))
