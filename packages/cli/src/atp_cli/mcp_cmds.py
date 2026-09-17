"""``atp mcp init`` and ``atp mcp wrap``: one command from an MCP server to a
protected MCP server, with the gateway running in-process from ``.atp/``.

Everything user-facing goes to stderr: stdout is the MCP channel.
"""

from __future__ import annotations

import logging
import shlex
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio

from atp_adapter_http import TrustPlaneClient
from atp_adapter_mcp import (
    ProxyConfig,
    UpstreamConfig,
    connect_upstream,
    dump_config,
    load_config,
    propose_config,
    render_header,
    serve,
)
from atp_cli.home import AtpHome
from atp_core import utcnow
from atp_evals.regression.format import parse_duration
from atp_gateway import create_app

log = logging.getLogger("atp.wrap")


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _upstream_from_args(url: str | None, command: list[str], cwd: str | None) -> UpstreamConfig:
    if url:
        return UpstreamConfig(url=url)
    if not command:
        raise ValueError("give an upstream: `-- <command> [args...]` or `--url URL`")
    return UpstreamConfig(command=command[0], args=tuple(command[1:]), cwd=cwd)


def _scope_dirs(command: list[str]) -> list[str]:
    """Absolute existing directories among the upstream's arguments (the way
    the reference filesystem server takes its allowed roots)."""
    out: list[str] = []
    for arg in command[1:]:
        p = Path(arg)
        if p.is_absolute() and p.is_dir():
            out.append(str(p.resolve()))
    return out


def _discover(upstream: UpstreamConfig) -> list[Any]:
    async def _run() -> list[Any]:
        probe = ProxyConfig(server_name="probe", upstream=upstream)
        async with connect_upstream(probe) as up:
            return list(up.tools)

    return anyio.run(_run)


def init_config(
    *,
    out: Path,
    name: str | None,
    url: str | None,
    command: list[str],
    cwd: str | None = None,
    casefold: bool | None = None,
    home_dir: str | None = None,
) -> int:
    if out.exists():
        _err(f"{out} exists; not overwriting (delete it or pass --config another path)")
        return 2
    try:
        upstream = _upstream_from_args(url, command, cwd)
    except ValueError as exc:
        _err(str(exc))
        return 2
    server_name = name or _default_name(url, command)
    _err(f"discovering tools from {url or shlex.join(command)} ...")
    try:
        tools = _discover(upstream)
    except Exception as exc:  # the upstream is arbitrary software; report, do not trace
        _err(f"could not connect to the upstream: {type(exc).__name__}: {str(exc)[:300]}")
        return 2
    proposal = propose_config(
        server_name, upstream, tools, scope_dirs=_scope_dirs(command), casefold=casefold
    )
    home = AtpHome(home_dir).ensure()
    version = f"{server_name}-v1"
    if home.ensure_policy_file(version, f"{server_name} via atp mcp wrap"):
        _err(f"wrote {home.policy_path}: declared policy set {version!r} (no rules yet)")
    config = proposal.config.model_copy(update={"policy_set": version})
    dump_config(config, out, header=render_header(proposal, url or shlex.join(command)))
    _err(f"wrote {out}: {len(tools)} tool(s) mapped under tool 'mcp.{server_name}'")
    for note in proposal.notes:
        _err(f"note: {note}")
    _err(f"next: atp mcp wrap --config {out}   (add --mode shadow to observe first)")
    return 0


def _default_name(url: str | None, command: list[str]) -> str:
    import re

    if url:
        host = url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        return re.sub(r"[^A-Za-z0-9._-]", "-", host)[:48] or "upstream"
    tokens = [t for t in command if not t.startswith("-")]
    candidate = Path(tokens[-1]).name if len(tokens) > 1 else Path(tokens[0]).name
    candidate = candidate.replace("@modelcontextprotocol/server-", "")
    return re.sub(r"[^A-Za-z0-9._-]", "-", candidate)[:48] or "upstream"


def wrap(
    *,
    config_path: Path,
    mode: str,
    home_dir: str | None,
    name: str | None,
    url: str | None,
    command: list[str],
    log_level: str = "warning",
) -> int:
    logging.basicConfig(level=log_level.upper(), stream=sys.stderr)
    if not config_path.exists():
        if not (url or command):
            _err(f"{config_path} not found and no upstream given; try: atp mcp wrap -- <command>")
            return 2
        rc = init_config(out=config_path, name=name, url=url, command=command, home_dir=home_dir)
        if rc != 0:
            return rc
    try:
        config = load_config(config_path)
    except (OSError, ValueError) as exc:
        _err(f"invalid config {config_path}: {str(exc)[:500]}")
        return 2
    if config.authority is None:
        _err(f"{config_path} has no `authority` section; `atp mcp wrap` needs one to delegate")
        return 2

    home = AtpHome(home_dir).ensure()
    settings = home.settings(enforcement_mode=mode, default_policy_set=config.policy_set)
    from atp_gateway import build_runtime

    try:
        runtime = build_runtime(settings)
    except Exception as exc:
        _err(f"could not start the local gateway from {home.path}: {str(exc)[:500]}")
        return 2
    app = create_app(settings, runtime=runtime)
    operator = TrustPlaneClient.for_app(app, operator_key=runtime.operator_key)

    try:
        token, grant_id = seed_session(operator, config)
    except Exception as exc:
        _err(f"could not delegate authority: {str(exc)[:500]}")
        runtime.close()
        return 2
    session_config = config.model_copy(update={"delegation_grant_id": grant_id})
    from atp_gateway.local import InProcessAgentClient

    agent = InProcessAgentClient.from_token(runtime, token)

    _err(
        f"atp mcp wrap: {config.server_name} [{mode.upper()}] home={home.path} "
        f"policy={runtime.trust_plane.policy_sets.default_version} "
        f"agent={config.agent_ref.id} principal={config.principal.id}"
    )
    if mode == "shadow":
        _err("SHADOW MODE: denials are recorded as WOULD_DENY and forwarded; nothing is blocked")
    try:
        anyio.run(serve, session_config, agent)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
    return 0


def seed_session(operator: TrustPlaneClient, config: ProxyConfig) -> tuple[str, str]:
    """Issue a session credential and the human → agent delegation described
    by ``authority``. Both expire with the session's ``expires_in``."""
    assert config.authority is not None
    now = utcnow()
    expires = now + parse_duration(config.authority.expires_in)
    human = config.principal.model_dump(mode="json")
    agent = config.agent_ref.model_dump(mode="json")
    issued = operator.issue_credential(
        agent, label=f"wrap:{config.server_name}", expires_at=expires.isoformat()
    )
    root = operator.issue_delegation(
        {
            "label": f"{config.principal.id}: local authority for {config.server_name}",
            "grantor": human,
            "grantee": human,
            "capabilities": list(config.authority.capabilities),
            "resource_scope": list(config.authority.resource_scope),
            "expires_at": (expires + timedelta(minutes=1)).isoformat(),
        }
    )["grant_id"]
    leaf = operator.issue_delegation(
        {
            "label": f"{config.agent_ref.id}: {config.server_name} session",
            "grantor": human,
            "grantee": agent,
            "parent_grant_id": root,
            "capabilities": list(config.authority.capabilities),
            "resource_scope": list(config.authority.resource_scope),
            "expires_at": expires.isoformat(),
        }
    )["grant_id"]
    return issued["token"], leaf
