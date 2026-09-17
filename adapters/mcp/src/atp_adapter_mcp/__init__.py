"""MCP integration: envelope mapping and a stdio proxy that authorizes tools/call."""

from atp_adapter_mcp.config import ProxyConfig, UpstreamConfig, load_config
from atp_adapter_mcp.interceptor import (
    DEFAULT_MAPPINGS,
    AgentContext,
    McpInterceptor,
    McpToolCall,
    McpToolResult,
    ToolMapping,
)
from atp_adapter_mcp.proxy import TrustPlaneProxy, connect_upstream, serve

__all__ = [
    "DEFAULT_MAPPINGS",
    "AgentContext",
    "McpInterceptor",
    "McpToolCall",
    "McpToolResult",
    "ProxyConfig",
    "ToolMapping",
    "TrustPlaneProxy",
    "UpstreamConfig",
    "connect_upstream",
    "load_config",
    "serve",
]
