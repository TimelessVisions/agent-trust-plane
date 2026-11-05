"""ATP layer: the suite server behind the real ``atp mcp wrap`` proxy, driven over stdio."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml
from mcp import StdioServerParameters, types
from mcp.client.stdio import get_default_environment

from atp_bench.annotations import Annotation
from atp_bench.dojo import DojoSuite
from atp_bench.layers.base import CallOutcome, Session, StdioMcpSession, result_text
from atp_bench.layers.open_layer import suite_server_argv

POLICY_SET = "bench"
# DENIED means a policy or delegation decision, nothing else. Harness and setup failures that
# share the ReasonCode enum (POLICY_SET_NOT_FOUND, TOOL_NOT_REGISTERED, OPERATOR_KEY_REQUIRED,
# AGENT_CREDENTIAL_*, GRANT_*, EXECUTION_*, TRACE_*, EVENT_*_RESERVED, ...) must not be credited
# to ATP, so they are INCONCLUSIVE. The set is derived explicitly from the enum.
_DENIAL_NAMES = frozenset(
    {
        "CAPABILITY_NOT_GRANTED",
        "RESOURCE_OUT_OF_SCOPE",
        "ACTION_DENIED_BY_POLICY",
        "APPROVAL_REQUIRED_BY_POLICY",
        "APPROVAL_REQUIRED_AMOUNT_THRESHOLD",
        # Delegation: only expiry, revocation and capability / scope escalation are decisions
        # about the call. The other DELEGATION_* codes (NOT_FOUND, *_MISMATCH, CHAIN_*, ...)
        # mean the harness built a broken chain, so they are INCONCLUSIVE.
        "DELEGATION_EXCEEDS_PARENT_CAPABILITIES",
        "DELEGATION_EXCEEDS_PARENT_RESOURCE_SCOPE",
        "DELEGATION_EXPIRED",
        "DELEGATION_REVOKED",
    }
)
_DENIAL_PREFIXES = ("ARGUMENT_", "PAYMENT_")
# Denials the proxy itself issues before consulting the gateway.
_PROXY_DENIALS = frozenset({"TOOL_UNKNOWN", "TOOL_ARGUMENTS_TOO_LARGE", "TOOL_ARGUMENTS_INVALID"})


def _denial_codes() -> frozenset[str]:
    from atp_core import ReasonCode

    values = {r.value for r in ReasonCode}
    missing = _DENIAL_NAMES - values
    if missing:  # an explicit raise, so the guard survives ``python -O``
        raise RuntimeError(f"ReasonCode lost {sorted(missing)}")
    denials = {v for v in values if v in _DENIAL_NAMES or v.startswith(_DENIAL_PREFIXES)}
    return frozenset(denials | _PROXY_DENIALS)


def _check_annotation(suite: DojoSuite, annotation: Annotation) -> None:
    """Render-time checks against the real suite: a mistake raises instead of rendering a
    config that silently never matches (the run then reports the item INCONCLUSIVE)."""
    tools = set(suite.tool_names)
    props = {name: set(schema.get("properties", {})) for name, _, schema in suite.tool_specs()}
    where = f"{suite.name}/{annotation.user_task}"
    for tool, arg in annotation.resource_args.items():
        if arg not in props.get(tool, set()):
            raise ValueError(
                f"{where}: resource_args {arg!r} is not a parameter of {tool!r}; "
                f"parameters: {sorted(props.get(tool, set()))}"
            )
    for rule in annotation.rules:
        applies = rule.get("applies_to") or {}
        rule_tool, action = applies.get("tool"), applies.get("action", "*")
        if rule_tool != f"dojo.{suite.name}":
            raise ValueError(
                f"{where}: rule {rule.get('id')!r} applies_to.tool {rule_tool!r} is unknown; "
                f"expected 'dojo.{suite.name}'"
            )
        if action not in tools:
            raise ValueError(
                f"{where}: rule {rule.get('id')!r} applies_to.action {action!r} is not a "
                f"{suite.name} tool"
            )


def render_atp_config(
    suite: DojoSuite, annotation: Annotation, server_argv: list[str], home: Path
) -> tuple[dict, dict]:
    """The ``atp-mcp.yaml`` and ``policies.yaml`` documents for one annotation.

    Per R2, a tool whose annotation names a resource argument gets
    ``dojo.<suite>:{arg}``; any other tool gets ``tool:<name>``.
    """
    if not Path(home).is_absolute():
        raise ValueError(f"home must be absolute: {home}")
    if not Path(server_argv[0]).is_absolute():
        raise ValueError(f"server_argv[0] must be an absolute executable path: {server_argv[0]}")
    _check_annotation(suite, annotation)
    tools: list[dict[str, Any]] = []
    for name in suite.tool_names:
        arg = annotation.resource_args.get(name)
        tools.append(
            {
                "mcp_tool": name,
                "tool": f"dojo.{suite.name}",
                "action": name,
                "capability": f"dojo.{suite.name}:{name}",
                "resource_template": f"dojo.{suite.name}:{{{arg}}}" if arg else f"tool:{name}",
            }
        )
    config: dict[str, Any] = {
        "server_name": f"dojo-{suite.name}",
        "policy_set": POLICY_SET,
        "principal": {"id": "bench-user", "kind": "human"},
        "agent": {"id": f"dojo-{suite.name}-agent", "kind": "agent"},
        "authority": {
            "capabilities": [f"dojo.{suite.name}:{c}" for c in annotation.capabilities],
            "resource_scope": list(annotation.resource_scope),
        },
        "upstream": {"command": server_argv[0], "args": list(server_argv[1:])},
        "tools": tools,
        "expose_unmapped_tools": False,
    }
    rules = []
    for raw in annotation.rules:
        rule = dict(raw)
        # The proxy stamps every envelope with tool "mcp.<server_name>" and ignores the mapping's
        # `tool`, so a rule written against the logical tool "dojo.<suite>" is retargeted to it.
        # _check_annotation has already ensured every rule names that logical tool.
        rule["applies_to"] = {**rule["applies_to"], "tool": f"mcp.{config['server_name']}"}
        rules.append(rule)
    policies = {
        "version": 1,
        "policy_sets": [
            {
                "version": POLICY_SET,
                "description": f"bench annotation for {suite.name}/{annotation.user_task}",
                "rules": rules,
            }
        ],
    }
    return config, policies


def classify(result: types.CallToolResult) -> CallOutcome:
    """DENIED only for an ATP denial; whatever else came back was let through."""
    payload = result.structured_content if result.is_error else None
    code = payload.get("reason_code") if isinstance(payload, dict) else None
    if isinstance(code, str):
        detail = f"{code}: {payload.get('message', '')}"[:300]
        if code in _denial_codes():
            return CallOutcome("DENIED", detail)
        # The proxy answered with a reason that is not a policy denial (UPSTREAM_ERROR when the
        # upstream hung or died, UPSTREAM_UNSUPPORTED_RESULT): the call's fate is unknown.
        return CallOutcome("INCONCLUSIVE", detail)
    return CallOutcome("ALLOWED", result_text(result)[:300])


def _write_yaml(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


class AtpLayer:
    name = "atp"

    def __init__(self, timeout_s: float = 30.0) -> None:
        self.timeout_s = timeout_s

    @contextmanager
    def open(
        self,
        suite: DojoSuite,
        annotation: Annotation,
        injection_task: str | None,
        journal: Path,
        workdir: Path,
    ) -> Iterator[Session]:
        from atp_cli.home import AtpHome

        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        home = workdir / "atp-home"
        AtpHome(home).ensure()
        argv = suite_server_argv(suite.name, injection_task, journal)
        config, policies = render_atp_config(suite, annotation, argv, home)
        # The proxy gives up on a hung upstream before the client-side timeout fires.
        config["request_timeout_seconds"] = max(1.0, self.timeout_s)
        config_path = workdir / "atp-mcp.yaml"
        _write_yaml(config_path, config)
        _write_yaml(workdir / "policies.yaml", policies)
        _write_yaml(home / "policies.yaml", policies)  # where ATP loads declared sets from
        wrap_args = [
            "-m", "atp_cli.main", "mcp", "wrap",
            "--config", str(config_path),
            "--home", str(home),
            "--mode", "enforce",
            "--log-level", "warning",
        ]  # fmt: skip
        params = StdioServerParameters(
            command=sys.executable,
            args=wrap_args,
            env={**get_default_environment(), "ATP_HOME": str(home)},
        )
        with StdioMcpSession(params, classify, call_timeout_s=self.timeout_s + 5) as session:
            yield session
