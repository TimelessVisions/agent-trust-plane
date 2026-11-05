"""ToolHive v0.55.2 Cedar competitor layer, derived from the same task annotation as ATP.

ToolHive's own pinned source exposes scalar arguments as `resource.arg_<name>`,
but only `arg_<name>_present` for arrays/maps/null. The renderer faithfully emits
the strongest policy that this surface can represent and records dropped rules.
See bench/competitors/toolhive.md for approximations and pinned source links.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from mcp import types

from atp_bench.annotations import Annotation
from atp_bench.dojo import Call, DojoSuite
from atp_bench.layers.agentgateway_layer import _free_port, _stop, _wait_port
from atp_bench.layers.atp_layer import _check_annotation
from atp_bench.layers.base import (
    CallOutcome,
    DroppedConstraint,
    EnvBlocked,
    HttpMcpSession,
    RenderedPolicy,
    Session,
    result_text,
)
from atp_bench.layers.open_layer import suite_server_argv

VERSION = "v0.55.2"
SOURCE = f"https://github.com/stacklok/toolhive/blob/{VERSION}"
AUTHZ_DOC = f"{SOURCE}/docs/authz.md"
AUTHZ_SOURCE = f"{SOURCE}/pkg/authz/authorizers/cedar/core.go"
CONVERSION_SOURCE = f"{SOURCE}/pkg/authz/authorizers/cedar/entity.go"
CLI_DOC = f"{SOURCE}/docs/cli/thv_run.md"
DENY_CODE = 403
DENY_MESSAGE = "Unauthorized"


def _string(value: str) -> str:
    """A Cedar source string literal (JSON-compatible string escaping)."""
    return json.dumps(value, ensure_ascii=False)


def _decimal(value: Any) -> str:
    number = format(Decimal(str(value)), "f")
    if "." not in number:
        number += ".0"
    return f"decimal({_string(number)})"


def _member(expr: str, values: tuple[Any, ...] | list[Any]) -> str:
    parts = []
    for value in values:
        if isinstance(value, bool):
            lit = "true" if value else "false"
        elif isinstance(value, int):
            lit = _decimal(value)
        else:
            lit = _string(str(value))
        parts.append(f"{expr} == {lit}")
    return "(" + " || ".join(parts) + ")" if parts else "false"


def _rule_condition(
    rule: dict[str, Any],
) -> tuple[str | None, DroppedConstraint | None, bool]:
    """Return Cedar condition, documented drop, and whether this denies the tool."""
    kind = str(rule["kind"])
    rid = str(rule["id"])
    if kind in {"deny", "require_approval"}:
        # ATP never lets these calls reach the upstream without a human approval flow.
        return None, None, True

    if kind == "argument_required":
        args = tuple(rule["arguments"])
        checks = [
            f"(resource has arg_{arg} || resource has arg_{arg}_present)"
            for arg in args
        ]
        return " && ".join(checks) if checks else "true", None, False
    if kind == "argument_forbidden":
        checks = [
            f"!(resource has arg_{arg} || resource has arg_{arg}_present)"
            for arg in rule["arguments"]
        ]
        return " && ".join(checks) if checks else "true", None, False

    arg = str(rule["argument"])
    x = f"resource.arg_{arg}"
    if kind in {"argument_max", "argument_min"}:
        op = "lessThanOrEqual" if kind == "argument_max" else "greaterThanOrEqual"
        bound = rule["max"] if kind == "argument_max" else rule["min"]
        check = f"{x}.{op}({_decimal(bound)})"
    elif kind == "argument_allowed_values":
        check = _member(x, rule["values"])
    elif kind in {"argument_subset_of", "argument_max_length"}:
        # Lists/maps are only represented as *_present by ToolHive's v0.55.2
        # preprocessArguments; it does not expose their elements or lengths.
        dropped = DroppedConstraint(
            source=rid,
            reason=(
                f"{kind} on {arg!r} cannot be enforced for complex arguments: "
                "ToolHive Cedar exposes only arg_<name>_present for arrays/objects"
            ),
            doc_url=AUTHZ_SOURCE,
        )
        return "true", dropped, False
    else:
        raise ValueError(f"unknown rule kind {kind!r}")

    # Null and missing arguments do not create arg_<name> in ToolHive; optional
    # means absent is allowed, but explicit null fails ATP's optional _present.
    if rule.get("optional"):
        check = f"(!(resource has arg_{arg} || resource has arg_{arg}_present) || {check})"
    else:
        check = f"(resource has arg_{arg} && {check})"
    return check, None, False


def _scope_condition(
    scope: tuple[str, ...], suite: str, arg: str
) -> str | None:
    """Translate concrete, wildcard and prefix scopes to Cedar scalar expressions."""
    x = f"resource.arg_{arg}"
    cases: list[str] = []
    for pattern in scope:
        if pattern in ("*", f"dojo.{suite}:*", "*:*"):
            return f"(resource has arg_{arg} || resource has arg_{arg}_present)"
        typ, _, ident = pattern.partition(":")
        if typ not in ("*", f"dojo.{suite}") or not ident:
            continue
        if ident == "*":
            return f"(resource has arg_{arg} || resource has arg_{arg}_present)"
        if ident.endswith("*"):
            cases.append(f"{x} like {_string(ident)}")
        else:
            cases.append(f"{x} == {_string(ident)}")
            # JSON numeric ids are converted to Cedar decimals, not strings.
            if re.fullmatch(r"[0-9]+", ident):
                cases.append(f"{x} == {_decimal(ident)}")
    if not cases:
        return None
    return f"(resource has arg_{arg} && ({' || '.join(cases)}))"


def render_toolhive_config(
    suite: DojoSuite, annotation: Annotation, upstream_url: str
) -> RenderedPolicy:
    """Render a pinned ToolHive v0.55.2 Cedar config plus the fidelity inventory."""
    _check_annotation(suite, annotation)
    from atp_identity.scope import scope_matches

    dropped: list[DroppedConstraint] = []
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for rule in annotation.rules:
        by_tool.setdefault(str(rule["applies_to"]["action"]), []).append(rule)

    policies: list[str] = []
    for tool in annotation.capabilities:
        conditions: list[str] = []
        resource_arg = annotation.resource_args.get(tool)
        if resource_arg:
            condition = _scope_condition(annotation.resource_scope, suite.name, resource_arg)
            if condition is None:
                continue
            conditions.append(condition)
        elif not scope_matches(annotation.resource_scope, f"tool:{tool}"):
            continue

        denied = False
        for rule in by_tool.get(tool, []):
            cond, drop, rule_denies = _rule_condition(rule)
            if drop is not None:
                dropped.append(drop)
            if rule_denies:
                denied = True
                break
            if cond and cond != "true":
                conditions.append(cond)
        if denied:
            continue

        head = (
            "permit(principal, action == Action::\"call_tool\", "
            f"resource == Tool::{_string(tool)})"
        )
        if conditions:
            policies.append(f"{head} when {{ {' && '.join(conditions)} }};")
        else:
            policies.append(head + ";")

    if not policies:
        # Cedar config must contain at least one policy; a forbid with no matching
        # permit is the strongest possible default-deny policy.
        policies = ['forbid(principal, action == Action::"call_tool", resource);']

    config = {
        "version": "1.0",
        "type": "cedarv1",
        "cedar": {"policies": policies, "entities_json": "[]"},
    }
    return RenderedPolicy(files={"cedar.json": json.dumps(config, indent=2) + "\n"}, dropped=dropped)


def classify(result: types.CallToolResult) -> CallOutcome:
    """A tool-result response, even an upstream tool error, reached the upstream."""
    return CallOutcome("ALLOWED", result_text(result)[:300])


def classify_error(exc: BaseException, call: Call) -> CallOutcome:
    """Only ToolHive's exact 403 JSON-RPC authorization shape counts as DENIED."""
    from mcp.shared.exceptions import MCPError

    if isinstance(exc, MCPError):
        err = exc.error
        if err.code == DENY_CODE and err.message == DENY_MESSAGE:
            return CallOutcome("DENIED", f"{err.code}: {err.message}")
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 403:
        try:
            body = response.json()
            error = body.get("error", {})
            if error.get("code") == DENY_CODE and error.get("message") == DENY_MESSAGE:
                return CallOutcome("DENIED", "403: Unauthorized")
        except (ValueError, AttributeError, TypeError):
            pass
    return CallOutcome("INCONCLUSIVE", f"{type(exc).__name__}: {exc}"[:300])


def _can_run_remote(log_text: str) -> bool:
    """Runtime/environment failures, not Cedar compilation errors."""
    lower = log_text.lower()
    return any(
        s in lower
        for s in (
            "docker daemon", "cannot connect to docker", "docker is not running",
            "container runtime", "podman socket", "unable to connect to the runtime",
            "no container runtime", "permission denied while trying to connect to",
        )
    )


class ToolhiveLayer:
    name = "toolhive"

    def __init__(self, timeout_s: float = 30.0, startup_timeout_s: float = 90.0) -> None:
        self.timeout_s = timeout_s
        self.startup_timeout_s = startup_timeout_s

    def dropped_constraints(
        self, suite: DojoSuite, annotation: Annotation
    ) -> list[DroppedConstraint]:
        return render_toolhive_config(suite, annotation, "http://127.0.0.1:9/mcp").dropped

    @contextmanager
    def open(
        self,
        suite: DojoSuite,
        annotation: Annotation,
        injection_task: str | None,
        journal: Path,
        workdir: Path,
    ) -> Iterator[Session]:
        if not sys.platform.startswith("linux"):
            raise EnvBlocked(f"ToolHive v0.55.2 is pinned for linux-amd64; platform={sys.platform}")
        from atp_bench.tools import fetch_tool

        exe = fetch_tool("toolhive")
        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        up_port, thv_port = _free_port(), _free_port()
        config = render_toolhive_config(suite, annotation, f"http://127.0.0.1:{up_port}/mcp")
        cedar_path = workdir / "cedar.json"
        cedar_path.write_text(config.files["cedar.json"], encoding="utf-8")

        with ExitStack() as stack:
            upstream_log = workdir / "suite_server.log"
            fh = stack.enter_context(upstream_log.open("wb"))
            upstream = subprocess.Popen(
                [*suite_server_argv(suite.name, injection_task, journal), "--http", str(up_port)],
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
            stack.callback(_stop, upstream)
            _wait_port(up_port, upstream, upstream_log, "suite server", self.startup_timeout_s)

            thv_log = workdir / "toolhive.log"
            thv_fh = stack.enter_context(thv_log.open("wb"))
            cmd = [
                str(exe), "run", f"http://127.0.0.1:{up_port}/mcp",
                "--name", f"atp-bench-{thv_port}",
                "--authz-config", str(cedar_path),
                "--proxy-port", str(thv_port),
                "--foreground",
            ]
            try:
                toolhive = subprocess.Popen(cmd, stdout=thv_fh, stderr=subprocess.STDOUT)
            except OSError as exc:
                raise EnvBlocked(f"ToolHive {VERSION} cannot execute here: {exc}") from exc
            stack.callback(_stop, toolhive)
            try:
                _wait_port(thv_port, toolhive, thv_log, "ToolHive", self.startup_timeout_s)
            except (TimeoutError, RuntimeError) as exc:
                message = thv_log.read_text(encoding="utf-8", errors="replace")[-2000:]
                if _can_run_remote(message):
                    raise EnvBlocked(f"ToolHive {VERSION} remote runtime unavailable: {message}") from exc
                raise

            session = HttpMcpSession(
                f"http://127.0.0.1:{thv_port}/mcp",
                classify,
                classify_error=classify_error,
                call_timeout_s=self.timeout_s + 5,
            )
            with session:
                yield session
