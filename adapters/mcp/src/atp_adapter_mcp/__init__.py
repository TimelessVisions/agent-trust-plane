"""MCP integration: a stdio proxy that authorizes every tools/call through the
trust gateway, plus the mapping and config it runs on."""

from atp_adapter_mcp.config import (
    AuthorityConfig,
    ProxyConfig,
    UpstreamConfig,
    dump_config,
    load_config,
)
from atp_adapter_mcp.discovery import Proposal, propose_config, render_header
from atp_adapter_mcp.mapping import UNMAPPED_CAPABILITY, PathNormalization, ToolMapping
from atp_adapter_mcp.proxy import TrustPlaneProxy, connect_upstream, serve

__all__ = [
    "UNMAPPED_CAPABILITY",
    "AuthorityConfig",
    "PathNormalization",
    "Proposal",
    "ProxyConfig",
    "ToolMapping",
    "TrustPlaneProxy",
    "UpstreamConfig",
    "connect_upstream",
    "dump_config",
    "load_config",
    "propose_config",
    "render_header",
    "serve",
]
