"""Generate a starting proxy config from an upstream server's own tool list.

The generated file is a *proposal for a human to review*. Tool descriptions
and annotations (``readOnlyHint``, ``destructiveHint``) come from the server
and are untrusted per the MCP specification; they are used only to choose
a suggested capability name and to write comments. Nothing here grants
authority: ``authority.capabilities`` in the generated config is what the
human delegates, and the default leaves ``<server>:destroy`` out.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from mcp import types

from atp_adapter_mcp.config import AuthorityConfig, ProxyConfig, UpstreamConfig
from atp_adapter_mcp.mapping import PathNormalization, ToolMapping

PATH_ARGUMENTS = ("path", "file_path", "filepath", "filename", "directory", "dir", "source")
ID_ARGUMENTS = (
    "id",
    "note_id",
    "uri",
    "url",
    "name",
    "repo",
    "repository",
    "channel",
    "table",
    "key",
    "issue",
    "owner",
)
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class Proposal:
    config: ProxyConfig
    notes: list[str] = field(default_factory=list)
    read_only: list[str] = field(default_factory=list)
    destructive: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


def _string_properties(tool: types.Tool) -> list[str]:
    schema: Any = tool.input_schema or {}
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return []
    out: list[str] = []
    for name, spec in props.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
            continue
        typ = spec.get("type") if isinstance(spec, dict) else None
        if typ in ("string", None, "integer"):
            out.append(name)
    return out


def _resource_for(tool: types.Tool, *, casefold: bool) -> tuple[str, PathNormalization | None]:
    props = _string_properties(tool)
    for cand in PATH_ARGUMENTS:
        if cand in props:
            return f"path:{{{cand}}}", PathNormalization(casefold=casefold)
    for cand in ID_ARGUMENTS:
        if cand in props:
            return f"{cand}:{{{cand}}}", None
    return f"tool:{_SAFE.sub('_', tool.name)[:64]}", None


def _flags(tool: types.Tool) -> tuple[bool, bool]:
    ann = tool.annotations
    read_only = bool(getattr(ann, "read_only_hint", False)) if ann else False
    destructive = bool(getattr(ann, "destructive_hint", False)) if ann else False
    return read_only, destructive


def propose_config(
    server_name: str,
    upstream: UpstreamConfig,
    tools: list[types.Tool],
    *,
    scope_dirs: list[str] | None = None,
    casefold: bool | None = None,
) -> Proposal:
    """Map every discovered tool; suggest capabilities from annotations;
    delegate read+write but not destroy; scope paths to ``scope_dirs`` when
    given (absolute directories), otherwise to everything of type ``path``."""
    fold = (os.name == "nt") if casefold is None else casefold
    proposal = Proposal(config=None)  # type: ignore[arg-type]
    mappings: list[ToolMapping] = []
    uses_paths = False
    for tool in sorted(tools, key=lambda t: t.name):
        read_only, destructive = _flags(tool)
        if read_only:
            cap, bucket = f"{server_name}:read", proposal.read_only
        elif destructive:
            cap, bucket = f"{server_name}:destroy", proposal.destructive
        else:
            cap, bucket = f"{server_name}:write", proposal.other
        bucket.append(tool.name)
        template, norm = _resource_for(tool, casefold=fold)
        uses_paths = uses_paths or norm is not None
        mappings.append(
            ToolMapping(
                mcp_tool=tool.name,
                tool=f"mcp.{server_name}",
                action=_SAFE.sub("_", tool.name)[:64],
                capability=cap,
                resource_template=template,
                path_normalization=norm,
                description=(tool.description or "")[:200].replace("\n", " "),
            )
        )
    scope: list[str] = []
    if uses_paths and scope_dirs:
        norm = PathNormalization(casefold=fold)
        for d in scope_dirs:
            base = norm.apply(d).rstrip("/")
            scope.append(f"path:{base}/*")
    elif uses_paths:
        scope.append("path:*")
        proposal.notes.append(
            "no directory given: path scope is 'path:*'; narrow it to 'path:/your/dir/*'"
        )
    if not uses_paths:
        scope.append("*")
    else:
        for kind in sorted({m.resource_template.split(":", 1)[0] for m in mappings}):
            if kind != "path":
                scope.append(f"{kind}:*")
    config = ProxyConfig(
        server_name=server_name,
        upstream=upstream,
        authority=AuthorityConfig(
            capabilities=(f"{server_name}:read", f"{server_name}:write"),
            resource_scope=tuple(scope),
        ),
        tools=tuple(mappings),
    )
    proposal.config = config
    if proposal.destructive:
        proposal.notes.append(
            f"tools the server marks destructive get '{server_name}:destroy', which is NOT "
            f"delegated: {', '.join(proposal.destructive)}"
        )
    proposal.notes.append(
        "readOnlyHint/destructiveHint come from the server and are unverified; review every "
        "capability before relying on it"
    )
    return proposal


def render_header(proposal: Proposal, command: str) -> str:
    lines = [
        "# Agent Trust Plane MCP proxy config (generated by `atp mcp init`; edit freely).",
        f"# Generated from: {command}",
        "# tools/list said:",
        f"#   read-only  : {', '.join(proposal.read_only) or '-'}",
        f"#   destructive: {', '.join(proposal.destructive) or '-'}",
        f"#   other      : {', '.join(proposal.other) or '-'}",
    ]
    lines += [f"# NOTE: {n}" for n in proposal.notes]
    lines += [
        "# `authority` is what the local human delegates to the session agent; tools whose",
        "# capability is not listed there are denied. Unlisted tools are denied and hidden.",
        "",
    ]
    return "\n".join(lines)
