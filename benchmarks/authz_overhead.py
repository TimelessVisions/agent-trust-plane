"""Benchmark: authorization overhead per tool call.

Component rows (in-process, no I/O beyond SQLite where stated):

  A1. delegation chain resolution      resolve a 2-link chain (memory store)
  A2. policy engine                    evaluate the 8-policy payments-v2 set
  A3. grant mint                       HMAC-SHA256 token over canonical claims
  A4. grant verify                     parse + HMAC compare + canonical check
  A5. audit append (memory)            one hash-chained event
  A6. audit append (SQLite file)       one hash-chained event, WAL, committed

End-to-end rows:

  B.  gateway authorize+execute        in-process ASGI (no sockets), memory store
  B2. gateway authorize+execute        in-process ASGI, persistent SQLite file
  C.  gateway authorize+execute        real uvicorn on 127.0.0.1 (two HTTP round trips)
  D.  MCP write_note, direct           MCP client -> notes server (stdio)
  E.  MCP write_note via proxy         client -> atp mcp proxy -> gateway (loopback) -> notes
  F.  MCP write_note via wrap          client -> atp mcp wrap (gateway in-process, SQLite) -> notes

E - D and F - D are the end-to-end cost of putting the trust plane in the
path of a real MCP tool call. "cold" columns are the first timed call after
process start (before warm-up), i.e. what the first tool call of a session
costs.

Not measured: throughput under concurrency, memory, or anything on a network.
Run:  uv run python benchmarks/authz_overhead.py [--n 300] [--out docs/benchmarks.md]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from atp_adapter_http import TrustPlaneClient
from atp_core import ActionEnvelope, PrincipalKind, PrincipalRef, new_trace_id
from atp_gateway import GatewaySettings, create_app
from atp_gateway.local import LocalGateway
from atp_identity import DelegationService, InMemoryDelegationStore
from atp_policy import InMemoryVendorDirectory, PolicyContext, PolicyEngine, PolicySetRegistry
from atp_policy.directory import Vendor
from finance_agent import AP_AGENT, HUMAN, seed_delegation_graph

WARMUP = 30


def pct(samples: list[float], p: float) -> float:
    s = sorted(samples)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def summarise(name: str, samples_s: list[float], cold_s: float | None = None) -> dict[str, Any]:
    ms = [x * 1000 for x in samples_s]
    return {
        "name": name,
        "n": len(ms),
        "mean_ms": statistics.fmean(ms),
        "p50_ms": pct(ms, 50),
        "p95_ms": pct(ms, 95),
        "p99_ms": pct(ms, 99),
        "min_ms": min(ms),
        "max_ms": max(ms),
        "cold_ms": cold_s * 1000 if cold_s is not None else None,
    }


def timed(fn: Any, n: int) -> tuple[list[float], float]:
    """Run fn WARMUP + n times; return timed samples and the very first (cold) time."""
    samples: list[float] = []
    cold = 0.0
    for i in range(WARMUP + n):
        t0 = time.perf_counter()
        fn(i)
        dt = time.perf_counter() - t0
        if i == 0:
            cold = dt
        if i >= WARMUP:
            samples.append(dt)
    return samples, cold


def _payment_envelope(grant_id: str) -> ActionEnvelope:
    return ActionEnvelope(
        trace_id=new_trace_id(),
        principal=HUMAN,
        agent=AP_AGENT,
        delegation_grant_id=grant_id,
        capability="pay:vendor",
        tool="payments",
        action="send_payment",
        resource="vendor:128",
        arguments={"amount": "480.00", "currency": "USD"},
    )


# ------------------------------------------------------------ A: engine only
def bench_engine(n: int) -> list[dict[str, Any]]:
    from atp_core import AuthorityConstraints, Money
    from atp_identity import DelegationRequest

    svc = DelegationService(InMemoryDelegationStore())
    now = datetime.now(UTC)
    root = svc.issue(
        DelegationRequest(
            label="root",
            grantor=HUMAN,
            grantee=HUMAN,
            capabilities=frozenset({"pay:vendor"}),
            resource_scope=("vendor:*",),
            constraints=AuthorityConstraints(max_amount=Money(amount="10000", currency="USD")),
            expires_at=now + timedelta(days=1),
        ),
        now=now,
    )
    ap = svc.issue(
        DelegationRequest(
            label="ap",
            grantor=HUMAN,
            grantee=AP_AGENT,
            parent_grant_id=root.grant_id,
            capabilities=frozenset({"pay:vendor"}),
            resource_scope=("vendor:*",),
            constraints=AuthorityConstraints(max_amount=Money(amount="1000", currency="USD")),
            expires_at=now + timedelta(hours=1),
        ),
        now=now,
    )
    vendors = InMemoryVendorDirectory(
        [Vendor(vendor_id="128", name="N", account_ref="acct-nw-4471")]
    )
    engine = PolicyEngine()
    policy_set = PolicySetRegistry.builtin().get("payments-v2")
    env = _payment_envelope(ap.grant_id)
    rows: list[dict[str, Any]] = []

    s, c = timed(lambda _: svc.resolve(ap.grant_id, agent=AP_AGENT, principal=HUMAN, now=now), n)
    rows.append(summarise("A1. delegation chain resolution (2 links, memory)", s, c))
    chain = svc.resolve(ap.grant_id, agent=AP_AGENT, principal=HUMAN, now=now)
    ctx = PolicyContext(envelope=env, vendors=vendors, now=now, authority=chain.authority)
    s, c = timed(lambda _: engine.evaluate(policy_set, ctx), n)
    rows.append(summarise("A2. policy engine (8 policies, payments-v2)", s, c))

    import sqlite3

    from atp_audit import EventType, InMemoryTraceStore, SqliteTraceStore
    from atp_gateway.grants import GrantSigner, new_grant_claims

    signer = GrantSigner(b"benchmark-signing-key-at-least-32-bytes-long!!")
    claims = new_grant_claims(
        trace_id=env.trace_id,
        decision_id="dec_bench",
        envelope_id=env.envelope_id,
        action_hash=env.action_hash,
        agent_id=AP_AGENT.id,
        policy_set_version="payments-v2",
        ttl_seconds=120,
        now=now,
    )
    s, c = timed(lambda _: signer.mint(claims), n)
    rows.append(summarise("A3. grant mint (HMAC-SHA256)", s, c))
    token = signer.mint(claims)
    s, c = timed(lambda _: signer.verify(token), n)
    rows.append(summarise("A4. grant verify", s, c))

    payload = {"envelope": env.model_dump(mode="json"), "action_hash": env.action_hash}
    mem = InMemoryTraceStore()
    s, c = timed(
        lambda i: mem.append(f"{i:012x}"[-12:], EventType.ACTION_PROPOSED, "a", payload), n
    )
    rows.append(summarise("A5. audit append (memory)", s, c))
    db = Path(tempfile.mkdtemp(prefix="atp-bench-db-")) / "atp.db"
    conn = sqlite3.connect(str(db), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    sq = SqliteTraceStore(conn)
    s, c = timed(lambda i: sq.append(f"{i:012x}"[-12:], EventType.ACTION_PROPOSED, "a", payload), n)
    rows.append(summarise("A6. audit append (SQLite file, WAL)", s, c))
    conn.close()
    return rows


# ---------------------------------------------- B/C: gateway authorize+execute
def _bench_gateway(client: TrustPlaneClient, n: int, label: str) -> dict[str, Any]:
    seed = seed_delegation_graph(client)
    agent = client.as_agent(seed.identities.accounts_payable_token)

    def one(_: int) -> None:
        env = _payment_envelope(seed.graph.accounts_payable)
        auth = agent.authorize(env)
        agent.execute(env, auth.execution_grant)

    samples, cold = timed(one, n)
    return summarise(label, samples, cold)


def bench_gateway_asgi(n: int) -> dict[str, Any]:
    app = create_app(GatewaySettings(database_path=":memory:"))
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as client:
        return _bench_gateway(client, n, "B. gateway authorize+execute (in-process ASGI)")


def bench_gateway_sqlite(n: int) -> dict[str, Any]:
    db = Path(tempfile.mkdtemp(prefix="atp-bench-gw-")) / "atp.db"
    app = create_app(
        GatewaySettings(
            database_path=str(db),
            grant_signing_key="benchmark-signing-key-at-least-32-bytes-long!!",
            operator_key="benchmark-operator-key-at-least-32-bytes-long!!",
        )
    )
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as client:
        return _bench_gateway(
            client, n, "B2. gateway authorize+execute (in-process ASGI, SQLite file)"
        )


def bench_gateway_http(n: int, gw: LocalGateway) -> dict[str, Any]:
    client = TrustPlaneClient(gw.url, operator_key=gw.operator_key)
    return _bench_gateway(client, n, "C. gateway authorize+execute (HTTP loopback)")


# ------------------------------------------------------ D/E: MCP tool calls
def _mcp_params_direct(notes_dir: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "notes_mcp_server"],
        env={**get_default_environment(), "NOTES_DIR": str(notes_dir)},
    )


def _mcp_params_proxy(cfg: Path, token: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "atp_adapter_mcp", "--config", str(cfg), "--log-level", "error"],
        env={**get_default_environment(), "ATP_AGENT_TOKEN": token},
    )


async def _bench_mcp(params: StdioServerParameters, n: int, label: str) -> dict[str, Any]:
    samples: list[float] = []
    cold = 0.0
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for i in range(WARMUP + n):
            t0 = time.perf_counter()
            res = await s.call_tool("write_note", {"id": f"n{i}", "text": "bench"})
            dt = time.perf_counter() - t0
            if res.is_error:
                raise RuntimeError(f"{label}: call failed: {res}")
            if i == 0:
                cold = dt
            if i >= WARMUP:
                samples.append(dt)
    return summarise(label, samples, cold)


def bench_mcp(n: int, gw: LocalGateway) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    tmp = Path(tempfile.mkdtemp(prefix="atp-bench-"))
    direct_dir, proxy_dir = tmp / "direct", tmp / "proxy"
    direct_dir.mkdir()
    proxy_dir.mkdir()
    operator = TrustPlaneClient(gw.url, operator_key=gw.operator_key)
    agent = PrincipalRef(id="bench-agent", kind=PrincipalKind.AGENT)
    human = PrincipalRef(id="bench-human", kind=PrincipalKind.HUMAN)
    token = operator.issue_credential(agent.model_dump(mode="json"), label="bench")["token"]
    now = datetime.now(UTC)
    root = operator.issue_delegation(
        {
            "label": "root",
            "grantor": human.model_dump(mode="json"),
            "grantee": human.model_dump(mode="json"),
            "capabilities": ["notes:write"],
            "resource_scope": ["note:*"],
            "expires_at": (now + timedelta(days=1)).isoformat(),
        }
    )["grant_id"]
    grant = operator.issue_delegation(
        {
            "label": "agent",
            "grantor": human.model_dump(mode="json"),
            "grantee": agent.model_dump(mode="json"),
            "parent_grant_id": root,
            "capabilities": ["notes:write"],
            "resource_scope": ["note:*"],
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )["grant_id"]
    cfg = tmp / "atp-mcp.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "gateway": gw.url,
                "server_name": "notes",
                "principal": human.model_dump(mode="json"),
                "agent": agent.model_dump(mode="json"),
                "delegation_grant_id": grant,
                "upstream": {
                    "command": sys.executable,
                    "args": ["-m", "notes_mcp_server"],
                    "env": {"NOTES_DIR": str(proxy_dir)},
                },
                "tools": [
                    {
                        "mcp_tool": "write_note",
                        "tool": "mcp.notes",
                        "action": "write_note",
                        "capability": "notes:write",
                        "resource_template": "note:{id}",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    direct = anyio.run(
        _bench_mcp, _mcp_params_direct(direct_dir), n, "D. MCP write_note, direct (stdio)"
    )
    proxied = anyio.run(
        _bench_mcp, _mcp_params_proxy(cfg, token), n, "E. MCP write_note via proxy + gateway (HTTP)"
    )
    # F: atp mcp wrap, gateway in-process with a persistent SQLite home.
    wrap_dir = tmp / "wrap"
    wrap_dir.mkdir()
    home = tmp / "home"
    wrap_cfg = tmp / "wrap-mcp.yaml"
    wrap_cfg.write_text(
        yaml.safe_dump(
            {
                "server_name": "notes",
                "upstream": {
                    "command": sys.executable,
                    "args": ["-m", "notes_mcp_server"],
                    "env": {"NOTES_DIR": str(wrap_dir)},
                },
                "authority": {"capabilities": ["notes:write"], "resource_scope": ["note:*"]},
                "tools": [
                    {
                        "mcp_tool": "write_note",
                        "tool": "mcp.notes",
                        "action": "write_note",
                        "capability": "notes:write",
                        "resource_template": "note:{id}",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    wrap_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atp_cli.main", "mcp", "wrap", "--config", str(wrap_cfg), "--home", str(home)],
        env={**get_default_environment()},
    )
    wrapped = anyio.run(
        _bench_mcp,
        wrap_params,
        n,
        "F. MCP write_note via atp mcp wrap (in-process gateway, SQLite)",
    )
    return direct, proxied, wrapped


# -------------------------------------------------------------------- report
def environment() -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "commit": os.popen("git rev-parse --short HEAD").read().strip(),
    }


def to_markdown(env: dict[str, Any], rows: list[dict[str, Any]], n: int) -> str:
    lines = [
        "# Benchmark: authorization overhead per tool call",
        "",
        f"Generated {env['date']} at commit `{env['commit']}` by `benchmarks/authz_overhead.py`.",
        "",
        "## Environment",
        "",
        f"- {env['platform']}",
        f"- Python {env['python']}, CPU: {env['cpu']} ({env['cpu_count']} logical cores)",
        "- Everything on one machine; HTTP is loopback; MCP is stdio subprocesses.",
        "",
        "## Method",
        "",
        f"- {WARMUP} warm-up iterations discarded, then n={n} timed iterations per row, "
        "sequential (no concurrency). `cold` is the first call after process start.",
        "- A1-A6: kernel components in isolation (see the module docstring).",
        "- B/B2/C: full `/authorize` + `/execute` round trip for a $480 payment envelope "
        "(grant minted, verified, consumed; ledger written); memory store, SQLite file, "
        "and real loopback HTTP respectively.",
        "- D/E/F: the same `write_note` MCP call directly to the notes server, through "
        "`atp mcp proxy` + a loopback gateway, and through `atp mcp wrap` (gateway in-process, "
        "persistent SQLite).",
        "- Persistent rows (A6, B2, F) use SQLite in WAL mode with the default `synchronous=FULL`; "
        "the kernel commits one transaction per operation (authorize, execute, outcome), so a "
        "proxied call costs three fsyncs, not one per event.",
        "- Timings are wall-clock `perf_counter` around the call as seen by the caller.",
        "",
        "## Results (milliseconds)",
        "",
        "| scenario | n | mean | p50 | p95 | p99 | min | max | cold |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        cold = f"{r['cold_ms']:.2f}" if r.get("cold_ms") is not None else "-"
        lines.append(
            f"| {r['name']} | {r['n']} | {r['mean_ms']:.2f} | {r['p50_ms']:.2f} | "
            f"{r['p95_ms']:.2f} | {r['p99_ms']:.2f} | {r['min_ms']:.2f} | {r['max_ms']:.2f} | {cold} |"
        )
    by = {r["name"].split(".")[0]: r for r in rows}
    if "D" in by and "E" in by and "F" in by:
        lines += [
            "",
            f"End-to-end overhead on an MCP tool call, p50: via proxy + HTTP gateway "
            f"(E - D) **{by['E']['p50_ms'] - by['D']['p50_ms']:.2f} ms**; via `atp mcp wrap` "
            f"(F - D) **{by['F']['p50_ms'] - by['D']['p50_ms']:.2f} ms**. "
            f"The two HTTP round trips alone (C, p50): **{by['C']['p50_ms']:.2f} ms**.",
        ]
    lines += [
        "",
        "## Limitations",
        "",
        "- Single machine, single client, sequential calls. No concurrency, no network "
        "latency, no TLS.",
        "- SQLite in-memory stores; a persistent database will be slower.",
        "- The notes server is trivial; a real tool's own latency dominates in practice.",
        "- No comparison to other gateways is made; this measures our overhead only.",
        "- Resource consumption was not measured.",
        "",
        "Reproduce: `uv run python benchmarks/authz_overhead.py --n 300 --out docs/benchmarks.md`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--out", default=None, help="write markdown here")
    parser.add_argument("--json", default=None, help="write raw results here")
    args = parser.parse_args()
    rows = [*bench_engine(args.n), bench_gateway_asgi(args.n), bench_gateway_sqlite(args.n)]
    with LocalGateway() as gw:
        rows.append(bench_gateway_http(args.n, gw))
        direct, proxied, wrapped = bench_mcp(args.n, gw)
        rows += [direct, proxied, wrapped]
    env = environment()
    md = to_markdown(env, rows, args.n)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps({"environment": env, "results": rows}, indent=2))


if __name__ == "__main__":
    main()
