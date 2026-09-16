"""Optional stdio MCP server that exposes mapped tools through the interceptor.

Requires the official ``mcp`` package (``pip install mcp``). It is not part of
the default install and is not exercised by the test suite; the interceptor it
wraps is. Run with::

    python -m atp_adapter_mcp --gateway http://127.0.0.1:8000 --grant <grant_id>
"""

from __future__ import annotations

from typing import Any

from atp_adapter_mcp.interceptor import AgentContext, McpInterceptor, McpToolCall


def build_server(interceptor: McpInterceptor, ctx: AgentContext) -> Any:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found,unused-ignore]
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("the MCP server wrapper needs: pip install mcp") from exc

    server = FastMCP("agent-trust-plane")

    def _make(name: str) -> Any:
        def call(arguments: dict[str, Any]) -> dict[str, Any]:
            result = interceptor.intercept(McpToolCall(name=name, arguments=arguments), ctx)
            return result.model_dump(by_alias=True)

        call.__name__ = name
        call.__doc__ = f"Guarded {name}: authorized and executed via the trust plane."
        return call

    for tool_name in interceptor.mapped_tools():
        server.tool(name=tool_name)(_make(tool_name))
    return server
