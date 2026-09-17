"""Proxy configuration: one upstream MCP server, one agent identity, a tool map.

Loaded from YAML. Secrets are never in the file: the agent credential comes
from an environment variable named by ``agent_token_env``; upstream HTTP
headers that carry secrets are named by environment variable in
``headers_env``.

Two ways to run:

* **remote gateway** (``atp mcp-proxy``): ``gateway`` is an HTTP URL and the
  proxy authenticates with ``$ATP_AGENT_TOKEN``;
* **local, in-process** (``atp mcp wrap``): the CLI starts the gateway from
  ``.atp/`` in the same process, issues a session credential and the
  delegation described by ``authority``, and hands the proxy a client. In
  that mode ``gateway``, ``agent_token_env`` and ``delegation_grant_id`` are
  not used.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from atp_adapter_mcp.mapping import ToolMapping
from atp_core import SCOPE_PATTERN, PrincipalKind, PrincipalRef


class UpstreamConfig(BaseModel):
    """How to reach the upstream MCP server: launch it over stdio (``command``)
    or connect to a Streamable HTTP endpoint (``url``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: str | None = Field(default=None, description="Executable, e.g. 'uv', 'npx'.")
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = Field(default=None, description="Streamable HTTP MCP endpoint.")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Static headers for HTTP upstreams (no secrets)."
    )
    headers_env: dict[str, str] = Field(
        default_factory=dict,
        description="Header name -> environment variable holding its value (for secrets).",
    )

    @model_validator(mode="after")
    def _one_transport(self) -> UpstreamConfig:
        if bool(self.command) == bool(self.url):
            raise ValueError("upstream needs exactly one of 'command' (stdio) or 'url' (HTTP)")
        if self.url and not (self.url.startswith("http://") or self.url.startswith("https://")):
            raise ValueError("upstream.url must be an http(s) URL")
        if self.url and self.url.startswith("http://"):
            host = self.url.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
            if host not in ("127.0.0.1", "localhost", "::1", "[::1]"):
                raise ValueError("plain http upstream is only allowed on localhost")
        return self

    @property
    def transport(self) -> str:
        return "http" if self.url else "stdio"

    def resolved_headers(self) -> dict[str, str]:
        out = dict(self.headers)
        for header, var in self.headers_env.items():
            value = os.environ.get(var, "")
            if not value:
                raise RuntimeError(f"upstream header {header!r} needs ${var} to be set")
            out[header] = value
        return out


class AuthorityConfig(BaseModel):
    """What ``atp mcp wrap`` delegates to the session agent, on behalf of the
    local human principal. Reviewed by the human; this *is* the policy of
    who may do what, so keep it narrow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capabilities: tuple[str, ...] = Field(min_length=1)
    resource_scope: tuple[str, ...] = Field(min_length=1)
    expires_in: str = Field(default="12h", pattern=r"^\d+[smhd]$")

    @model_validator(mode="after")
    def _patterns(self) -> AuthorityConfig:
        import re

        for p in self.resource_scope:
            if not re.fullmatch(SCOPE_PATTERN, p):
                raise ValueError(f"invalid resource pattern {p!r}")
        for c in self.capabilities:
            if not re.fullmatch(r"^[A-Za-z0-9._:-]{1,128}$", c):
                raise ValueError(f"invalid capability {c!r}")
        return self


class ProxyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gateway: str = Field(default="http://127.0.0.1:8000")
    server_name: str = Field(
        pattern=r"^[A-Za-z0-9._-]+$",
        max_length=48,
        description="Short name for the upstream; envelopes use tool='mcp.<server_name>'.",
    )
    principal: PrincipalRef = Field(
        default=PrincipalRef(id="local-user", kind=PrincipalKind.HUMAN),
        description="The human on whose behalf the agent acts.",
    )
    agent: PrincipalRef | None = Field(
        default=None, description="Defaults to '<server_name>-agent'."
    )
    delegation_grant_id: str | None = Field(
        default=None,
        max_length=128,
        description="Remote-gateway mode: the grant the agent acts under.",
    )
    agent_token_env: str = Field(
        default="ATP_AGENT_TOKEN",
        description="Environment variable holding the agent's bearer credential.",
    )
    upstream: UpstreamConfig
    authority: AuthorityConfig | None = Field(
        default=None, description="Local mode: what to delegate to the session agent."
    )
    policy_set: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9._-]+$",
        description="Local mode: default policy set (built-in or from .atp/policies.yaml).",
    )
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

    @model_validator(mode="after")
    def _unique_tools(self) -> ProxyConfig:
        seen: set[str] = set()
        for m in self.tools:
            if m.mcp_tool in seen:
                raise ValueError(f"tool {m.mcp_tool!r} is mapped twice")
            seen.add(m.mcp_tool)
        return self

    @property
    def envelope_tool(self) -> str:
        return f"mcp.{self.server_name}"

    @property
    def agent_ref(self) -> PrincipalRef:
        return self.agent or PrincipalRef(id=f"{self.server_name}-agent", kind=PrincipalKind.AGENT)

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


def dump_config(config: ProxyConfig, path: str | Path, *, header: str = "") -> None:
    data = config.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    data["server_name"] = config.server_name
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    Path(path).write_text(header + text, encoding="utf-8")
