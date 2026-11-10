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

import contextlib
import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atp_adapter_mcp.mapping import ToolMapping
from atp_core import (
    SCOPE_PATTERN,
    Budget,
    Money,
    PrincipalKind,
    PrincipalRef,
    check_file_version,
    read_bounded_text,
    warn_if_unversioned,
)

CONFIG_KIND = "atp-mcp.yaml"

# Tools the gateway executes itself (its ToolRegistry's registered tools, as
# opposed to the external prefixes it releases to a trusted executor). The
# adapter must not import atp_gateway, so this is the one copy of that list;
# a test builds the gateway runtime and asserts the two agree. A mapping onto
# one of these would have the gateway run the action on ALLOW (a payment
# settles) while the proxy reports the call as denied, so it is refused.
GATEWAY_EXECUTED_TOOLS: frozenset[str] = frozenset({"payments"})


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
    max_amount: Money | None = Field(
        default=None,
        description="Explicit maximum value per payment. If omitted, payment policies deny.",
    )
    currencies: frozenset[str] | None = Field(
        default=None,
        description="Explicit currency allowlist for delegated payment actions.",
    )
    budget: Budget | None = Field(
        default=None,
        description="Cumulative spend per UTC day/week/month for actions whose arguments "
        "carry an `amount`. Counted per principal and agent, so it binds across sessions.",
    )

    @model_validator(mode="after")
    def _patterns(self) -> AuthorityConfig:
        import re

        for p in self.resource_scope:
            if not re.fullmatch(SCOPE_PATTERN, p):
                raise ValueError(f"invalid resource pattern {p!r}")
        for c in self.capabilities:
            if not re.fullmatch(r"^[A-Za-z0-9._:-]{1,128}$", c):
                raise ValueError(f"invalid capability {c!r}")
        if self.currencies is not None:
            for currency in self.currencies:
                if not re.fullmatch(r"[A-Z]{3}", currency):
                    raise ValueError(f"invalid delegated currency {currency!r}")
            if self.max_amount is not None and self.max_amount.currency not in self.currencies:
                raise ValueError("maximum payment currency must be present in delegated currencies")
        return self


class ProxyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = Field(
        default=1,
        description="File format version. A file without it loads as 1 with a "
        "DeprecationWarning; `atp migrate` adds it.",
    )
    gateway: str = Field(default="http://127.0.0.1:8000")
    server_name: str = Field(
        pattern=r"^[A-Za-z0-9._-]+$",
        max_length=48,
        description="Short name for the upstream. Mapped calls use their mapping's `tool`; "
        "unmapped calls use tool='mcp.<server_name>'.",
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

    @field_validator("version", mode="before")
    @classmethod
    def _supported_version(cls, value: Any) -> int:
        return check_file_version(value, CONFIG_KIND)

    @model_validator(mode="after")
    def _unique_tools(self) -> ProxyConfig:
        seen: set[str] = set()
        for m in self.tools:
            if m.mcp_tool in seen:
                raise ValueError(f"tool {m.mcp_tool!r} is mapped twice")
            seen.add(m.mcp_tool)
        return self

    @model_validator(mode="after")
    def _no_mapping_onto_gateway_executed_tools(self) -> ProxyConfig:
        """Refuse, in every mode, a mapping whose ``tool`` the gateway runs itself."""
        native = sorted({m.envelope_tool for m in self.tools}.intersection(GATEWAY_EXECUTED_TOOLS))
        if native:
            raise ValueError(
                f"mapping tool(s) {native} name a tool the gateway executes itself; "
                "a proxied MCP tool needs its own tool name (e.g. 'mcp.<server_name>')"
            )
        return self

    @model_validator(mode="after")
    def _gateway_credentials_stay_out_of_the_upstream(self) -> ProxyConfig:
        """Refuse a config that hands the proxy's own secrets to the upstream.

        Upstream API tokens belong in ``upstream.env`` / ``headers_env``.
        The operator key, grant signing key, and agent credential do not:
        a process that can read the upstream's environment can then call
        the gateway as the operator or the agent. The proxy cannot see
        whether some other process can also spawn the upstream command.
        """
        forbidden = gateway_credential_env_names(self.agent_token_env)
        up = self.upstream
        leaked = sorted(set(up.env).intersection(forbidden))
        leaked += [f"headers_env:{var}" for var in up.headers_env.values() if var in forbidden]
        for header, value in up.headers.items():
            for var in forbidden:
                secret = os.environ.get(var, "")
                if secret and value == secret:
                    leaked.append(f"header:{header}=${var}")
        # The Ed25519 grant key: its PEM, its file, or the directory holding it.
        places: list[tuple[str, str]] = [(f"env:{k}", v) for k, v in up.env.items()]
        places += [(f"header:{k}", v) for k, v in up.headers.items()]
        places += [
            (f"headers_env:{var}", os.environ.get(var, "")) for var in up.headers_env.values()
        ]
        places += [(f"args[{i}]", a) for i, a in enumerate(up.args)]
        for where, value in places:
            what = grant_key_material(value)
            if what:
                leaked.append(f"{where} ({what})")
        if leaked:
            raise ValueError(
                "refusing to start: gateway credentials would be given to the upstream "
                f"({', '.join(leaked)}). Keep ATP_OPERATOR_KEY, ATP_GRANT_SIGNING_KID, "
                "ATP_GRANT_KEYS_DIR, ATP_HOME, the grant key files (grant-<kid>.key), "
                f"and ${self.agent_token_env} out of upstream.env, upstream.headers, "
                "upstream.headers_env and upstream.args."
            )
        return self

    @property
    def envelope_tool(self) -> str:
        """The tool stamped on envelopes for unmapped calls (and what `atp mcp init`
        writes into every mapping). Mapped calls use ``ToolMapping.envelope_tool``."""
        return f"mcp.{self.server_name}"

    @property
    def mapped_tools(self) -> tuple[str, ...]:
        """Distinct envelope tools across ``tools``, sorted."""
        return tuple(sorted({m.envelope_tool for m in self.tools}))

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


_GATEWAY_CREDENTIAL_ENV = (
    "ATP_OPERATOR_KEY",
    "ATP_GRANT_SIGNING_KEY",  # the 0.3.x HMAC key; still never handed on
    "ATP_GRANT_SIGNING_KID",
    "ATP_GRANT_KEYS_DIR",
    "ATP_HOME",  # holds keys.env and keys/
)
_GRANT_KEY_FILE = re.compile(r"grant-[0-9a-f]{16}\.key\b")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def gateway_credential_env_names(agent_token_env: str) -> frozenset[str]:
    return frozenset({*_GATEWAY_CREDENTIAL_ENV, agent_token_env})


def _grant_key_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("ATP_GRANT_KEYS_DIR"):
        dirs.append(Path(os.environ["ATP_GRANT_KEYS_DIR"]))
    dirs.append(Path(os.environ.get("ATP_HOME") or ".atp") / "keys")
    out = []
    for d in dirs:
        with contextlib.suppress(OSError, ValueError, RuntimeError):
            out.append(d.expanduser().resolve())
    return out


def grant_key_material(value: str) -> str | None:
    """Why ``value`` would hand the upstream the grant signing key, or None."""
    if not value:
        return None
    if "PRIVATE KEY-----" in value:
        return "a PEM private key"
    if _GRANT_KEY_FILE.search(value):
        return "a grant key file"
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    for keys_dir in _grant_key_dirs():
        if path == keys_dir or path.is_relative_to(keys_dir):
            return "the grant key directory"
        if keys_dir.is_relative_to(path):
            # The ATP home itself, or any ancestor of the keys directory:
            # access to it is access to the keys below it.
            return "a directory containing the grant keys"
    return None


def url_host(url: str) -> str:
    rest = url.split("//", 1)[1].split("/", 1)[0]
    if rest.startswith("["):
        end = rest.find("]")
        return rest[: end + 1] if end != -1 else rest
    return rest.split(":", 1)[0]


def shared_upstream_warning(url: str) -> str | None:
    """Warn when an HTTP upstream is not loopback.

    Plain HTTP off localhost is already refused. HTTPS to any other host
    is allowed, and the proxy cannot see a firewall, so this is a warning
    rather than a refusal. Loopback is not proof of isolation either: any
    other process on the host can still connect.
    """
    if url_host(url) in _LOOPBACK_HOSTS:
        return None
    return (
        "upstream is not loopback; the proxy cannot prove it is the only client. "
        "Anything that can open this URL bypasses authorization unless the "
        "upstream accepts connections only from the proxy and the proxy alone "
        "holds the upstream credential. Never give the upstream ATP_OPERATOR_KEY, "
        "ATP_GRANT_SIGNING_KID, or read access to the grant keys "
        "(.atp/keys/grant-<kid>.key): with them it can act as the operator or mint grants."
    )


def load_config(path: str | Path) -> ProxyConfig:
    raw: Any = yaml.safe_load(read_bounded_text(path))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a mapping at top level")
    warn_if_unversioned(raw, path, CONFIG_KIND)
    return ProxyConfig.model_validate(raw)


def dump_config(config: ProxyConfig, path: str | Path, *, header: str = "") -> None:
    data = {
        "version": config.version,
        **config.model_dump(mode="json", exclude_none=True, exclude_defaults=True),
    }
    data["server_name"] = config.server_name
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    Path(path).write_text(header + text, encoding="utf-8")
