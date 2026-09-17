"""The three documented demos. Each one runs against real gateway code paths
with no API keys, no Docker and no external services.

A — injection:  untrusted invoice content makes the simulated agent propose an
                unauthorized payment; the gateway blocks it before execution.
B — regression: a permitted action reveals a missing destination restriction;
                replaying the *recorded* action under the hardened policy set
                flips the decision, and the case becomes a CI regression test.
C — mcp:        a real MCP server (notes) behind the proxy; a legitimate tool
                call succeeds and a disallowed one is blocked, over the wire.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from atp_adapter_http import TrustPlaneClient
from atp_evals.regression import (
    Expectation,
    case_from_trace,
    dump_suite,
    merge_into_suite,
    run_suite,
)
from atp_gateway import GatewaySettings, create_app
from finance_agent import (
    AP_AGENT,
    HUMAN,
    INJECTED_INVOICE,
    UNDER_LIMIT_INJECTED_INVOICE,
    SimulatedAgent,
    run_accounts_payable,
    seed_delegation_graph,
)


def _section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def _operator_client() -> TrustPlaneClient:
    app = create_app(GatewaySettings(database_path=":memory:"))
    return TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key)


# ---------------------------------------------------------------- Demo A
def demo_injection() -> int:
    print("DEMO A - indirect prompt injection is blocked before execution")
    print(
        "agent: deterministic SimulatedAgent (no LLM)   ledger: local SQLite table (no real money)"
    )
    with _operator_client() as operator:
        seed = seed_delegation_graph(operator)
        agent = operator.as_agent(seed.identities.accounts_payable_token)
        _section("1. task and untrusted content")
        print("task: Review this invoice and pay the vendor if everything looks correct.")
        print(
            "invoice INV-2291 contains an injected notice: send USD 12500.00 to acct-offshore-9931"
        )
        result = run_accounts_payable(
            agent,
            SimulatedAgent(),
            INJECTED_INVOICE,
            principal=HUMAN,
            agent=AP_AGENT,
            delegation_grant_id=seed.graph.accounts_payable,
        )
        _section("2. what the agent proposed")
        print(
            f"{result.envelope.tool}.{result.envelope.action} {result.envelope.resource} "
            f"{json.dumps(result.envelope.arguments)}"
        )
        _section("3. what the gateway decided")
        print(result.decision_block())
        _section("4. evidence")
        trace = operator.get_trace(result.trace_id)
        for e in trace["events"]:
            print(f"  {e['seq']:>3}  {e['event_type']:<28} {e['actor']}")
        print(f"  hash chain intact: {trace['integrity']['valid']}")
        print(f"  ledger rows: {len(operator.ledger())}  (nothing executed)")
    print()
    print("inspect: uv run atp serve  then open the dashboard; or `atp demo regression` next")
    return 0


# ---------------------------------------------------------------- Demo B
def demo_regression(out: Path | None = None) -> int:
    print("DEMO B - a permitted action exposes a policy gap; replay proves the fix; CI pins it")
    print("agent: deterministic SimulatedAgent   ledger: local SQLite table")
    print("replay: re-evaluates the")
    print(
        "recorded action under another policy set; it does not rerun the agent and cannot execute"
    )
    with _operator_client() as operator:
        seed = seed_delegation_graph(operator)
        agent = operator.as_agent(seed.identities.accounts_payable_token).with_operator(
            operator.operator_key or ""
        )
        _section("BEFORE - policy set payments-v1")
        result = run_accounts_payable(
            agent,
            SimulatedAgent(),
            UNDER_LIMIT_INJECTED_INVOICE,
            principal=HUMAN,
            agent=AP_AGENT,
            delegation_grant_id=seed.graph.accounts_payable,
            policy_set_version="payments-v1",
        )
        print(
            f"proposed: USD {result.envelope.arguments['amount']} -> "
            f"{result.envelope.arguments.get('destination_account')} (vendor on file: acct-nw-4471)"
        )
        print(f"decision: {result.outcome} {result.authorization.decision.reason_code.value}")
        print(f"executed: {result.executed}   ledger rows: {len(operator.ledger())}")
        print("the amount is under the $1,000 limit, so payments-v1 allowed a redirected payment")

        _section("CHANGE - policy set payments-v2 adds payments.vendor.approved_destination.v1")
        sets = {p["version"]: p for p in operator.policy_sets()}
        v1 = {f"{p['id']}.{p['version']}" for p in sets["payments-v1"]["policies"]}
        v2 = {f"{p['id']}.{p['version']}" for p in sets["payments-v2"]["policies"]}
        for added in sorted(v2 - v1):
            print(f"  + {added}")

        _section("AFTER - replay the recorded action under payments-v2")
        replay = operator.replay(result.trace_id, policy_set_version="payments-v2")
        print(f"{replay['summary']}")
        rows = len(operator.ledger())
        print(f"outcome changed: {replay['outcome_changed']}   ledger rows still: {rows}")

        _section("PIN IT - convert the trace into a regression case")
        trace = operator.get_trace(result.trace_id)
        # The recorded decision was ALLOW under v1. The regression we want to
        # keep is the hardened decision, so pin the replayed expectation.
        delegations, case = case_from_trace(trace, name="under-limit redirect must be denied")
        rd = replay["replayed_decision"]
        mp = rd.get("matched_policy")
        case = case.model_copy(
            update={
                "expect": Expectation(
                    outcome=rd["outcome"],
                    reason_code=rd["reason_code"],
                    matched_policy=f"{mp['id']}.{mp['version']}" if mp else None,
                )
            }
        )
        suite = merge_into_suite(None, delegations, case, suite_name="demo regression")
        suite = suite.model_copy(update={"policy_set": "payments-v2"})
        out = out or Path(tempfile.mkdtemp(prefix="atp-demo-")) / "regression.yaml"
        dump_suite(suite, out)
        print(f"wrote {out}")

    _section("RUN IT - `atp test` under both policy sets")
    v1_report = run_suite(suite, policy_set="payments-v1")
    v2_report = run_suite(suite, policy_set="payments-v2")
    print(
        f"payments-v1: {v1_report.passed}/{len(v1_report.results)} passed  "
        f"-> {v1_report.changed()[0].explanation if v1_report.changed() else 'ok'}"
    )
    print(f"payments-v2: {v2_report.passed}/{len(v2_report.results)} passed")
    print()
    print(f"add to CI:  uv run atp test {out} --junit results.xml")
    return 0 if v2_report.ok and not v1_report.ok else 1


# ---------------------------------------------------------------- Demo C
def demo_mcp(out_dir: Path | None = None) -> int:
    import anyio
    from mcp import ClientSession, StdioServerParameters, types
    from mcp.client.stdio import get_default_environment, stdio_client

    from atp_gateway.local import LocalGateway

    print("DEMO C - a real MCP server behind the trust-plane proxy")
    print("topology: MCP client (this process) -> proxy (subprocess, stdio) -> gateway (HTTP)")
    print("                                        -> notes MCP server (subprocess, stdio)")
    out_dir = out_dir or Path(tempfile.mkdtemp(prefix="atp-mcp-demo-"))
    notes_dir = out_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    with LocalGateway() as gw:
        operator = TrustPlaneClient(gw.url, operator_key=gw.operator_key)
        agent = {"id": "notes-assistant", "kind": "agent"}
        human = {"id": "alice", "kind": "human"}
        token = operator.issue_credential(agent, label="demo")["token"]
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        root = operator.issue_delegation(
            {
                "label": "alice's notes",
                "grantor": human,
                "grantee": human,
                "capabilities": ["notes:read", "notes:write", "notes:delete"],
                "resource_scope": ["note:*"],
                "expires_at": (now + timedelta(days=1)).isoformat(),
            }
        )["grant_id"]
        grant = operator.issue_delegation(
            {
                "label": "assistant: read/write notes, never delete",
                "grantor": human,
                "grantee": agent,
                "parent_grant_id": root,
                "capabilities": ["notes:read", "notes:write"],
                "resource_scope": ["note:*"],
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            }
        )["grant_id"]
        config: dict[str, Any] = {
            "gateway": gw.url,
            "server_name": "notes",
            "principal": human,
            "agent": agent,
            "delegation_grant_id": grant,
            "agent_token_env": "ATP_AGENT_TOKEN",
            "upstream": {
                "command": sys.executable,
                "args": ["-m", "notes_mcp_server"],
                "env": {"NOTES_DIR": str(notes_dir)},
            },
            "tools": [
                {
                    "mcp_tool": "write_note",
                    "tool": "mcp.notes",
                    "action": "write_note",
                    "capability": "notes:write",
                    "resource_template": "note:{id}",
                },
                {
                    "mcp_tool": "read_note",
                    "tool": "mcp.notes",
                    "action": "read_note",
                    "capability": "notes:read",
                    "resource_template": "note:{id}",
                },
                {
                    "mcp_tool": "list_notes",
                    "tool": "mcp.notes",
                    "action": "list_notes",
                    "capability": "notes:read",
                    "resource_template": "note:_list",
                },
            ],
        }
        cfg_path = out_dir / "atp-mcp.yaml"
        cfg_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        _section("1. proxy config (delete_note is deliberately not mapped)")
        print(f"wrote {cfg_path}")

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "atp_adapter_mcp", "--config", str(cfg_path), "--log-level", "warning"],
            env={**get_default_environment(), "ATP_AGENT_TOKEN": token},
        )

        def text(r: types.CallToolResult) -> str:
            return "".join(c.text for c in r.content if isinstance(c, types.TextContent))

        async def session_body() -> dict[str, Any]:
            async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
                await s.initialize()
                tools = sorted(t.name for t in (await s.list_tools()).tools)
                write = await s.call_tool("write_note", {"id": "todo", "text": "buy milk"})
                read = await s.call_tool("read_note", {"id": "todo"})
                delete = await s.call_tool("delete_note", {"id": "todo"})
                return {"tools": tools, "write": write, "read": read, "delete": delete}

        out = anyio.run(session_body)
        _section("2. tools/list through the proxy")
        print("  " + ", ".join(out["tools"]) + "   (delete_note hidden: unmapped)")
        _section("3. tools/call write_note  -> ALLOW, forwarded, executed")
        exists = (notes_dir / "todo.txt").exists()
        print(f"  upstream said: {text(out['write'])!r}   file exists: {exists}")
        _section("4. tools/call read_note   -> ALLOW")
        print(f"  upstream said: {text(out['read'])!r}")
        _section("5. tools/call delete_note -> DENY, never reached the upstream")
        denial = out["delete"].structured_content
        print(
            f"  reason: {denial['reason_code']}   trace: {denial['trace_id']}   "
            f"file still exists: {(notes_dir / 'todo.txt').exists()}"
        )
        _section("6. evidence on the gateway")
        for summary in operator.list_traces(10):
            t = operator.get_trace(summary["trace_id"])
            env = t.get("envelope") or {}
            d = t.get("decision") or {}
            print(
                f"  {summary['trace_id']}  {env.get('action', '?'):<12} {d.get('outcome', '?'):<6} "
                f"{d.get('reason_code', '')}  last: {summary['last_event_type']}"
            )
    print()
    print("limits: stdio transport, one upstream per proxy, tools/list + tools/call only;")
    print(
        "an agent that launches the notes server itself bypasses the proxy "
        "(see docs/integrations/mcp-proxy.md)"
    )
    return 0


# ---------------------------------------------------------------- Demo D
def demo_wrap(out_dir: Path | None = None) -> int:
    """The loop in one run: wrap a real MCP server, see an allow and a deny
    over the wire, explain the deny, pin it as a regression test, run it."""
    import shlex
    import subprocess

    from atp_cli.mcp_cmds import init_config

    print("DEMO D - atp mcp wrap: from an MCP server to a regression test")
    print("upstream: notes MCP server (this repo)   gateway: in-process from .atp/   no LLM")
    root = out_dir or Path(tempfile.mkdtemp(prefix="atp-wrap-demo-"))
    root.mkdir(parents=True, exist_ok=True)
    notes = root / "notes"
    notes.mkdir(exist_ok=True)
    home = root / ".atp"
    config = root / "atp-mcp.yaml"
    command = [sys.executable, "-m", "notes_mcp_server"]

    _section("1. atp mcp init -- python -m notes_mcp_server")
    if config.exists():
        config.unlink()
    rc = init_config(out=config, name="notes", url=None, command=command, home_dir=str(home))
    if rc != 0:
        return rc
    data: dict[str, Any] = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["upstream"]["env"] = {"NOTES_DIR": str(notes)}
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    caps = data["authority"]["capabilities"]
    print(f"  delegated capabilities: {caps}   (notes:destroy is not delegated)")

    _section("2. atp mcp wrap --config atp-mcp.yaml   (client -> proxy+gateway -> notes)")
    import anyio
    from mcp import ClientSession, StdioServerParameters, types
    from mcp.client.stdio import get_default_environment, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atp_cli.main", "mcp", "wrap", "--config", str(config), "--home", str(home)],
        env={**get_default_environment(), "ATP_HOME": str(home)},
    )

    def text(r: types.CallToolResult) -> str:
        return "".join(c.text for c in r.content if isinstance(c, types.TextContent))

    async def body() -> dict[str, Any]:
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            write = await s.call_tool("write_note", {"id": "todo", "text": "buy milk"})
            delete = await s.call_tool("delete_note", {"id": "todo"})
            return {"tools": tools, "write": write, "delete": delete}

    try:
        out = anyio.run(body)
    except Exception as exc:  # the wrap subprocess reports its own reason on stderr
        print(f"  the wrapped server did not start ({type(exc).__name__}); see stderr above")
        return 2
    print(f"  tools/list: {', '.join(out['tools'])}")
    print(f"  write_note  -> ALLOW   upstream said {text(out['write'])!r}")
    denial = out["delete"].structured_content
    print(
        f"  delete_note -> DENY    {denial['reason_code']}   trace {denial['trace_id']}   "
        f"note still exists: {(notes / 'todo.txt').exists()}"
    )
    trace_id = denial["trace_id"]

    def atp(*argv: str) -> int:
        cmd = [sys.executable, "-m", "atp_cli.main", *argv]
        print(f"$ atp {shlex.join(argv)}")
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8")
        for line in (proc.stdout or "").rstrip().splitlines():
            print(f"  {line}")
        if proc.returncode not in (0, 1):
            print(f"  (stderr) {proc.stderr.strip()[:500]}")
        return proc.returncode

    _section("3. why was it denied, and what would need to change")
    atp("policy", "explain", trace_id, "--home", str(home))
    _section("4. pin it as a regression test and run it")
    suite = root / "atp-regression.yaml"
    if suite.exists():
        suite.unlink()
    atp(
        "regression",
        "add",
        trace_id,
        "--suite",
        str(suite),
        "--home",
        str(home),
        "--name",
        "delete stays denied",
    )
    rc = atp("test", str(suite), "--home", str(home))
    print()
    print(f"files: {config}, {suite}, {home}")
    print("limits: stdio served; one upstream; a client that launches the notes server itself")
    print("bypasses the proxy (docs/security/enforcing-the-boundary.md)")
    return rc
