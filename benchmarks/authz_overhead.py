"""Benchmark: authorization overhead per tool call.

Measures four things on one machine, same process tree, same Python:

  A. policy engine only        in-process PolicyEngine.evaluate on a resolved chain
  B. gateway authorize+execute in-process ASGI (no sockets): /authorize then /execute
  C. gateway over loopback     real uvicorn on 127.0.0.1: /authorize then /execute
  D. MCP tool call, direct     MCP client -> notes server (stdio), write_note
  E. MCP tool call, via proxy  MCP client -> proxy -> gateway (loopback) -> notes server

A, B, C use the same $480 payment envelope. D and E use the same write_note
call. E - D is the end-to-end cost of putting the trust plane in the path of
a real MCP tool call; C is the cost of the two HTTP round trips it adds.

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


def summarise(name: str, samples_s: list[float]) -> dict[str, Any]:
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
    }


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
def bench_engine(n: int) -> dict[str, Any]:
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
    samples: list[float] = []
    for i in range(WARMUP + n):
        t0 = time.perf_counter()
        chain = svc.resolve(ap.grant_id, agent=AP_AGENT, principal=HUMAN, now=now)
        ctx = PolicyContext(envelope=env, vendors=vendors, now=now, authority=chain.authority)
        engine.evaluate(policy_set, ctx)
        dt = time.perf_counter() - t0
        if i >= WARMUP:
            samples.append(dt)
    return summarise("A. policy engine + chain resolution (in-process)", samples)


# ---------------------------------------------- B/C: gateway authorize+execute
def _bench_gateway(client: TrustPlaneClient, n: int, label: str) -> dict[str, Any]:
    seed = seed_delegation_graph(client)
    agent = client.as_agent(seed.identities.accounts_payable_token)
    samples: list[float] = []
    for i in range(WARMUP + n):
        env = _payment_envelope(seed.graph.accounts_payable)
        t0 = time.perf_counter()
        auth = agent.authorize(env)
        agent.execute(env, auth.execution_grant)
        dt = time.perf_counter() - t0
        if i >= WARMUP:
            samples.append(dt)
    return summarise(label, samples)


def bench_gateway_asgi(n: int) -> dict[str, Any]:
    app = create_app(GatewaySettings(database_path=":memory:"))
    with TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key) as client:
        return _bench_gateway(client, n, "B. gateway authorize+execute (in-process ASGI)")


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
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for i in range(WARMUP + n):
            t0 = time.perf_counter()
            res = await s.call_tool("write_note", {"id": f"n{i}", "text": "bench"})
            dt = time.perf_counter() - t0
            if res.is_error:
                raise RuntimeError(f"{label}: call failed: {res}")
            if i >= WARMUP:
                samples.append(dt)
    return summarise(label, samples)


def bench_mcp(n: int, gw: LocalGateway) -> tuple[dict[str, Any], dict[str, Any]]:
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
                        "resource_arguments": ["id"],
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
        _bench_mcp, _mcp_params_proxy(cfg, token), n, "E. MCP write_note via proxy + gateway"
    )
    return direct, proxied


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
        "sequential (no concurrency).",
        "- A: resolve a 2-link delegation chain and evaluate the 8-policy `payments-v2` set on "
        "a $480 envelope.",
        "- B/C: full `/authorize` + `/execute` round trip for the same envelope (grant minted, "
        "verified, consumed; ledger written).",
        "- D/E: the same `write_note` MCP call, directly to the notes server vs. through the "
        "proxy (which adds authorize + execute + outcome report over loopback HTTP).",
        "- Timings are wall-clock `perf_counter` around the call as seen by the caller.",
        "",
        "## Results (milliseconds)",
        "",
        "| scenario | n | mean | p50 | p95 | p99 | min | max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['n']} | {r['mean_ms']:.2f} | {r['p50_ms']:.2f} | "
            f"{r['p95_ms']:.2f} | {r['p99_ms']:.2f} | {r['min_ms']:.2f} | {r['max_ms']:.2f} |"
        )
    by = {r["name"][:1]: r for r in rows}
    if "D" in by and "E" in by:
        lines += [
            "",
            f"End-to-end overhead of the proxy on an MCP tool call (E minus D, p50): "
            f"**{by['E']['p50_ms'] - by['D']['p50_ms']:.2f} ms**; "
            f"the two gateway round trips alone (C, p50): **{by['C']['p50_ms']:.2f} ms**.",
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
    rows = [bench_engine(args.n), bench_gateway_asgi(args.n)]
    with LocalGateway() as gw:
        rows.append(bench_gateway_http(args.n, gw))
        direct, proxied = bench_mcp(args.n, gw)
        rows += [direct, proxied]
    env = environment()
    md = to_markdown(env, rows, args.n)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps({"environment": env, "results": rows}, indent=2))


if __name__ == "__main__":
    main()
