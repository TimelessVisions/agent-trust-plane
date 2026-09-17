# ADR-0002: Product wedge — regression-tested tool authorization

Status: Accepted
Date: 2026-09-17

## Context

`docs/competitive-landscape.md` shows a crowded field of MCP gateways
(ContextForge, agentgateway, ToolHive, Docker MCP Gateway) that already do
transports, isolation, secrets and coarse tool RBAC well, and a separate
field of evaluation tools (promptfoo, Inspect, AgentDojo) that find problems
but enforce nothing. Between them are four concrete, evidenced gaps:
argument-aware decisions derived from delegated authority; a reusable,
inspectable decision→execution artifact; tamper-evident records with replay;
and turning an incident into a CI regression test.

The proposed direction was:

> Agent security regression testing + enforceable tool authorization.
> "Connect your agent. Find dangerous actions. Enforce permissions. Prove the fix."

## Decision

Adopt the proposed direction with two corrections from the research.

**Correction 1 — we are a decision-and-evidence layer, not a gateway.**
We will not compete on transports, federation or isolation. Our MCP
integration is a *local stdio proxy* for one upstream server: enough to
intercept real tool calls in a developer's own workflow, document its scope
honestly, and later be embedded as an interceptor/ext_authz in the gateways
that already exist.

**Correction 2 — "find dangerous actions" means record, not discover.**
promptfoo and AgentDojo discover attacks better than we will. Our job starts
when a consequential call happens: record it with provenance, decide it
against delegated authority, and make that decision reproducible. The
developer journey is therefore:

1. Put the proxy in front of an MCP server (one config change in the client).
2. Every `tools/call` becomes an authorized, traced action; unmapped tools
   are denied by default.
3. `atp record` turns any trace into a regression case (deterministic
   conversion; no LLM).
4. `atp test` runs the cases against an ephemeral gateway with a chosen
   policy set, and fails CI if a decision changes.
5. The dashboard shows before/after for a recorded action across policy
   versions.

## Scope for this release

P0 (must be complete and tested): MCP stdio proxy with real protocol
integration; `atp` CLI with `doctor`, `demo`, `record`, `test`; YAML
regression format with JSON and JUnit output; GitHub Actions example.
P1: before/after dashboard centrepiece; authorization-overhead benchmark;
contributor docs.
P2 (roadmap only): interceptor adapters for Docker MCP Gateway and
agentgateway ext_authz; Streamable HTTP proxy; declarative policy format.

## Consequences

- The README leads with the proxy + regression test journey, not the finance
  demo. The finance demo becomes Demo A/B; the proxy is Demo C.
- The policy engine must gain a generic argument-constraint policy so a
  developer can express "amount ≤ limit" for tools other than payments
  without writing Python. (Roadmap; this release ships capability +
  resource + the existing payment policies, and documents the gap.)
- Everything that reads a recorded trace treats it as untrusted input.
