"""Proxy configuration: one upstream MCP server, one agent identity, a tool map.

Loaded from YAML. Secrets are never in the file: the agent credential comes
from an environment variable named by ``agent_token_env``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from atp_adapter_mcp.interceptor import ToolMapping
from atp_core import PrincipalRef


class UpstreamConfig(BaseModel):
    """How to launch the upstream MCP server over stdio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: str = Field(description="Executable, e.g. 'uv', 'npx', 'python'.")
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class ProxyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gateway: str = Field(default="http://127.0.0.1:8000")
    server_name: str = Field(
        pattern=r"^[A-Za-z0-9._-]+$",
        max_length=48,
        description="Short name for the upstream; envelopes use tool='mcp.<server_name>'.",
    )
    principal: PrincipalRef
    agent: PrincipalRef
    delegation_grant_id: str = Field(min_length=1, max_length=128)
    agent_token_env: str = Field(
        default="ATP_AGENT_TOKEN",
        description="Environment variable holding the agent's bearer credential.",
    )
    upstream: UpstreamConfig
    tools: tuple[ToolMapping, ...] = Field(
        default=(),
        description="Explicit mappings. Tools not listed are denied by default.",
    )
    expose_unmapped_tools: bool = Field(
        default=False,
        description="If true, tools/list still advertises unmapped tools (calls are denied and "
        "recorded). Useful for evidence gathering; false hides them from the model.",
    )
    request_timeout_seconds: float = Field(default=30.0, ge=1, le=600)

    @property
    def envelope_tool(self) -> str:
        return f"mcp.{self.server_name}"

    def agent_token(self) -> str:
        token = os.environ.get(self.agent_token_env, "")
        if not token:
            raise RuntimeError(
                f"agent credential missing: set ${self.agent_token_env} to the token issued by "
                "POST /agents/{id}/credentials"
            )
        return token

    def mapping_for(self, tool_name: str) -> ToolMapping | None:
        return next((m for m in self.tools if m.mcp_tool == tool_name), None)


def load_config(path: str | Path) -> ProxyConfig:
    raw: Any = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping at top level")
    return ProxyConfig.model_validate(raw)
