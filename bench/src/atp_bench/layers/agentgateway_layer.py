"""agentgateway v1.6.0 layer: the HTTP suite server behind the real agentgateway binary.

The policy is rendered per task from the same annotation ATP gets, as the strongest
``mcpAuthorization`` agentgateway 1.6.0 can express (spec: "Competitors get the same per-task
information"). See ``bench/competitors/agentgateway.md`` for the justification.

Ruling: agentgateway 1.6.0 CEL CAN see tool arguments at authorization time, through
``json(request.body).params.arguments``: the gateway keeps the original HTTP request bytes in the
CEL context of ``mcpAuthorization`` (``mcp/streamablehttp.rs``) and ``request.body`` /
``json()`` are documented CEL (``schema/cel.md``, ``schema/cel-functions.md``). The documented
``mcp.tool.arguments`` variable is NOT populated there (``McpAuthorizationSet::validate`` builds
``MCPInfo`` from name and target only; issue #2069). So argument rules and the resource scope ARE
enforced here, contrary to the plan's assumption that they had to be dropped. Verified against
the binary (``tests/test_agentgateway_layer.py``).

Rule shape, one allow rule per granted tool (allow rules are OR-ed)::

    mcp.tool.name == "<tool>" && (mcp.methodName != "tools/call" ||
        json(request.body).params.with(p, has(p.arguments) ? p.arguments : {}).with(a, <conds>))

``tools/list`` is filtered by name only (a list request has no arguments). Any CEL evaluation
error (a missing key, a non-numeric amount) makes the rule false, which denies: fail closed.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from mcp import types

from atp_bench.annotations import Annotation
from atp_bench.dojo import Call, DojoSuite
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

VERSION = "v1.6.0"
_SRC = f"https://github.com/agentgateway/agentgateway/blob/{VERSION}"
DOC_URLS = {
    "cel_variables": f"{_SRC}/schema/cel.md",
    "cel_functions": f"{_SRC}/schema/cel-functions.md",
    "config_schema": f"{_SRC}/schema/config.md",
    "mcp_authorization_example": f"{_SRC}/examples/mcp-authorization/README.md",
    "rbac_source": f"{_SRC}/crates/agentgateway/src/mcp/rbac.rs",
    "body_in_cel_source": f"{_SRC}/crates/agentgateway/src/mcp/streamablehttp.rs",
    "deny_response_test": f"{_SRC}/crates/agentgateway/src/mcp/mcp_tests.rs",
    "issue_2069": "https://github.com/agentgateway/agentgateway/issues/2069",
}
TARGET = "dojo"
# agentgateway answers a denied tools/call with the same JSON-RPC error it uses for a tool that
# does not exist, so a denial cannot be told apart from "unknown" on the wire. Every call the
# bench makes names a tool the upstream serves, so this exact shape is a policy denial.
DENY_CODE = -32602


def _lit(value: Any) -> str:
    """A CEL literal. JSON string escapes are valid CEL string escapes."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"no CEL literal for {type(value).__name__}")


def _double(dec: Decimal) -> str:
    text = repr(float(dec))
    return text if any(c in text for c in ".en") else text + ".0"


def _member(expr: str, values: tuple[Any, ...] | list[Any]) -> str:
    """``expr`` equals one of ``values`` with the same JSON type (ATP compares type and value,
    so ``true`` never matches ``1`` and ``"5"`` never matches ``5``)."""
    groups: dict[str, list[str]] = {}
    for v in values:
        kind = "bool" if isinstance(v, bool) else "int" if isinstance(v, int) else "string"
        groups.setdefault(kind, []).append(_lit(v))
    parts = []
    for kind, lits in groups.items():
        if kind == "int":  # agentgateway's json() yields uint for a non-negative JSON integer
            parts.append(f"({_is_int(expr)} && int({expr}) in [{', '.join(lits)}])")
        else:
            parts.append(f"(type({expr}) == {kind} && {expr} in [{', '.join(lits)}])")
    return "(" + " || ".join(parts) + ")" if parts else "false"


def _is_int(expr: str) -> str:
    return f"(type({expr}) == int || type({expr}) == uint)"


# ATP's resource id grammar (``atp_core.resources.RESOURCE_PATTERN``): 1-255 code points, no
# '*', no control characters. agentgateway's CEL regex (Rust ``regex``) is Unicode-aware, so
# ``{1,255}`` counts code points exactly like Python's ``re`` (to be checked against the pinned binary before D2 approval).
_RESOURCE_ID_RE = r"\A[^*\x00-\x1f\x7f]{1,255}\z"
# Largest max_length rendered as a code-point regex; ``(?s:.){0,100000}`` exceeds the regex size
# limit in agentgateway 1.6.0 (checked on the binary), 10000 compiles.
_MAX_REGEX_LENGTH = 10_000
# Python's Decimal allows '_' only between two digits.
_BAD_UNDERSCORE_RE = r"(?:\A|[^0-9])_|_(?:[^0-9]|\z)"


def _number(expr: str, test: str) -> str:
    """``test`` over ``n``, the finite number ATP's ``_to_decimal`` reads from ``expr``.

    A JSON number is used as is; a string is trimmed and its digit-separating underscores
    removed, as ``Decimal(str(v))`` does. Infinities and NaN fail ``n - n == 0.0``, as ATP
    rejects them. Anything ``double()`` cannot parse is a CEL error: the rule is false (deny),
    as ATP denies a non-number."""
    s = f"{expr}.trim()"
    num = (
        f"(type({expr}) == string ? "
        f'({s}.matches({_lit(_BAD_UNDERSCORE_RE)}) ? double("x") : '
        f'double({s}.replace("_", ""))) : double({expr}))'
    )
    return f"{num}.with(n, n - n == 0.0 && {test})"


def _present(arg: str) -> str:
    return f"(has(a.{arg}) && a.{arg} != null)"


def _rule_condition(rule: dict[str, Any]) -> tuple[str | None, DroppedConstraint | None]:
    """CEL over ``a`` (the call's arguments) for one ATP rule, mirroring
    ``atp_policy.declarative.DeclaredRule``. ``None`` condition means "deny the tool"."""
    kind, rid = rule["kind"], str(rule["id"])
    if kind in ("deny", "require_approval"):
        # No approval flow in agentgateway; ATP's REQUIRE_APPROVAL never lets the call through
        # either, so a plain deny is the faithful (not weaker) rendering.
        return None, None
    if kind == "argument_required":
        return " && ".join(_present(x) for x in rule["arguments"]), None
    if kind == "argument_forbidden":  # an explicit null is present, as in ATP
        return " && ".join(f"!has(a.{x})" for x in rule["arguments"]), None
    arg = str(rule["argument"])
    x = f"a.{arg}"
    dropped = None
    if kind == "argument_max":
        check = _number(x, f"n <= {_double(Decimal(str(rule['max'])))}")
    elif kind == "argument_min":
        check = _number(x, f"n >= {_double(Decimal(str(rule['min'])))}")
    elif kind == "argument_allowed_values":
        check = _member(x, rule["values"])
    elif kind == "argument_subset_of":
        check = f"(type({x}) == list ? {x} : [{x}]).all(i, {_member('i', rule['values'])})"
    elif kind == "argument_max_length":
        n = int(rule["max_length"])
        # size() counts UTF-8 bytes for a string; ATP counts code points. bytes <= n implies
        # code points <= n, else a Unicode-aware regex counts code points exactly.
        if n <= _MAX_REGEX_LENGTH:
            cp = _lit(rf"\A(?s:.){{0,{n}}}\z")
            text = f"(size({x}) <= {n} || {x}.matches({cp}))"
        else:
            text = f"size({x}) <= {n}"
        listy = f"(type({x}) == list || type({x}) == map)"
        check = f"(type({x}) == string ? {text} : (!{listy} || size({x}) <= {n}))"
        reason = (
            f"argument_max_length on {arg!r} is enforced for strings, lists and objects; "
            "for a number or boolean ATP measures its canonical JSON text, which agentgateway "
            "CEL cannot compute, so such values pass"
        )
        if n > _MAX_REGEX_LENGTH:
            reason += (
                f"; strings are enforced on UTF-8 bytes (stricter for non-ASCII), since a "
                f"code-point regex longer than {_MAX_REGEX_LENGTH} does not compile"
            )
        dropped = DroppedConstraint(
            source=rid,
            reason=reason,
            doc_url=DOC_URLS["cel_functions"],
        )
    else:  # pragma: no cover - RuleSpec validation keeps the kinds closed
        raise ValueError(f"unknown rule kind {kind!r}")
    if rule.get("optional"):
        return f"(!{_present(arg)} || {check})", dropped
    return f"({_present(arg)} && {check})", dropped


def _scope_condition(scope: tuple[str, ...], suite: str, arg: str) -> str | None:
    """CEL for ``dojo.<suite>:{arg}`` matching ``scope`` (``atp_identity.scope.matches``);
    ``None`` when no pattern can match (the tool is then not granted)."""
    x = f"a.{arg}"
    # ATP derives the resource from a string or integer argument only, and rejects an id that
    # breaks RESOURCE_PATTERN before any matching (so '*' never matches, even under '*').
    valid = (
        f"{_present(arg)} && (type({x}) == string || {_is_int(x)}) && "
        f"string({x}).matches({_lit(_RESOURCE_ID_RE)})"
    )
    exact: list[str] = []
    prefixes: list[str] = []
    for pattern in scope:
        if pattern == "*":
            return f"({valid})"
        p_type, _, p_id = pattern.partition(":")
        if p_type not in ("*", f"dojo.{suite}"):
            continue
        if p_id == "*":
            return f"({valid})"
        if p_id.endswith("*"):
            prefixes.append(p_id[:-1])
        else:
            exact.append(p_id)
    tests = []
    if exact:
        tests.append(f"string({x}) in [{', '.join(_lit(e) for e in exact)}]")
    tests += [f"string({x}).startsWith({_lit(p)})" for p in prefixes]
    if not tests:
        return None
    return f"({valid} && ({' || '.join(tests)}))"


def _tool_resource_in_scope(scope: tuple[str, ...], tool: str) -> bool:
    from atp_identity.scope import scope_matches

    return scope_matches(scope, f"tool:{tool}")


def render_agentgateway_config(
    suite: DojoSuite, annotation: Annotation, upstream_url: str, port: int
) -> RenderedPolicy:
    """The agentgateway ``config.yaml`` for one annotation, and what it could not express."""
    _check_annotation(suite, annotation)
    dropped: list[DroppedConstraint] = []
    rules_by_tool: dict[str, list[dict[str, Any]]] = {}
    for rule in annotation.rules:
        rules_by_tool.setdefault(rule["applies_to"]["action"], []).append(rule)

    allow: list[str] = []
    for tool in annotation.capabilities:
        conds: list[str] = []
        arg = annotation.resource_args.get(tool)
        if arg:
            scope = _scope_condition(annotation.resource_scope, suite.name, arg)
            if scope is None:
                continue  # ATP's kernel denies every call: no resource can be in scope
            conds.append(scope)
        elif not _tool_resource_in_scope(annotation.resource_scope, tool):
            continue
        denied = False
        for rule in rules_by_tool.get(tool, []):
            cond, drop = _rule_condition(rule)
            if drop is not None:
                dropped.append(drop)
            if cond is None:
                denied = True
            else:
                conds.append(cond)
        if denied:
            continue
        name = f"mcp.tool.name == {_lit(tool)}"
        if conds:
            body = (
                "json(request.body).params.with(p, has(p.arguments) ? p.arguments : {})"
                f".with(a, {' && '.join(conds)})"
            )
            allow.append(f'{name} && (mcp.methodName != "tools/call" || {body})')
        else:
            allow.append(name)
    if not allow:
        # An empty rule list means "no policy" (allow all) in agentgateway, so deny explicitly.
        allow = ["false"]
    config = {
        "config": {"enableIpv6": False},
        "mcp": {
            "port": port,
            "policies": {"mcpAuthorization": {"rules": allow}},
            "targets": [{"name": TARGET, "mcp": {"host": upstream_url}}],
        },
    }
    text = yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=10_000)
    return RenderedPolicy(files={"config.yaml": text}, dropped=dropped)


def classify(result: types.CallToolResult) -> CallOutcome:
    """A result came back: the call reached the upstream (an upstream tool error included)."""
    return CallOutcome("ALLOWED", result_text(result)[:300])


def classify_error(exc: BaseException, call: Call) -> CallOutcome:
    """DENIED only for agentgateway's real deny shape for this very tool; else INCONCLUSIVE."""
    from mcp.shared.exceptions import MCPError

    if isinstance(exc, MCPError):
        detail = f"{exc.error.code}: {exc.error.message}"[:300]
        if exc.error.code == DENY_CODE and exc.error.message == f"Unknown tool: {call.function}":
            return CallOutcome("DENIED", detail)
        return CallOutcome("INCONCLUSIVE", detail)
    return CallOutcome("INCONCLUSIVE", f"{type(exc).__name__}: {exc}"[:300])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_port(port: int, proc: subprocess.Popen, log: Path, what: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = log.read_text(encoding="utf-8", errors="replace")[-1500:]
            raise RuntimeError(f"{what} exited with {proc.returncode}: {tail}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"{what} did not listen on {port} within {timeout_s:.0f}s")


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=20)


class AgentgatewayLayer:
    name = "agentgateway"

    def __init__(self, timeout_s: float = 30.0, startup_timeout_s: float = 180.0) -> None:
        self.timeout_s = timeout_s
        self.startup_timeout_s = startup_timeout_s

    def dropped_constraints(
        self, suite: DojoSuite, annotation: Annotation
    ) -> list[DroppedConstraint]:
        return render_agentgateway_config(suite, annotation, "http://127.0.0.1:1/mcp", 1).dropped

    @contextmanager
    def open(
        self,
        suite: DojoSuite,
        annotation: Annotation,
        injection_task: str | None,
        journal: Path,
        workdir: Path,
    ) -> Iterator[Session]:
        if sys.platform.startswith(("win", "cygwin")):
            raise EnvBlocked("agentgateway: linux binary; run in the Linux/WSL lane")
        from atp_bench.tools import fetch_tool

        exe = fetch_tool("agentgateway")
        workdir = Path(workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        up_port, gw_port = _free_port(), _free_port()
        policy = render_agentgateway_config(
            suite, annotation, f"http://127.0.0.1:{up_port}/mcp", gw_port
        )
        doc = yaml.safe_load(policy.files["config.yaml"])
        # Admin, stats and readiness listeners default to fixed ports; give each run its own.
        doc["config"].update(
            {f"{k}Addr": f"127.0.0.1:{_free_port()}" for k in ("admin", "stats", "readiness")}
        )
        config = workdir / "agentgateway.yaml"
        config.write_text(yaml.safe_dump(doc, sort_keys=False, width=10_000), encoding="utf-8")

        with ExitStack() as stack:
            up_log = workdir / "suite_server.log"
            argv = [*suite_server_argv(suite.name, injection_task, journal), "--http", str(up_port)]
            fh = stack.enter_context(up_log.open("wb"))
            upstream = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT)
            stack.callback(_stop, upstream)
            _wait_port(up_port, upstream, up_log, "suite server", self.startup_timeout_s)

            gw_log = workdir / "agentgateway.log"
            gfh = stack.enter_context(gw_log.open("wb"))
            try:
                gateway = subprocess.Popen(
                    [str(exe), "-f", str(config)], stdout=gfh, stderr=subprocess.STDOUT
                )
            except OSError as exc:  # exec format error, missing loader, ...
                raise EnvBlocked(f"agentgateway {VERSION} cannot execute here: {exc}") from exc
            stack.callback(_stop, gateway)
            _wait_port(gw_port, gateway, gw_log, "agentgateway", 60)

            session = HttpMcpSession(
                f"http://127.0.0.1:{gw_port}/mcp",
                classify,
                classify_error=classify_error,
                call_timeout_s=self.timeout_s + 5,
            )
            with session:
                yield session
