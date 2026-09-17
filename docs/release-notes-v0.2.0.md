# v0.2.0 — MCP proxy, `atp` CLI, security regression tests

Agent Trust Plane is an experimental control plane that puts an independent
authorization decision between an agent and its tools, keeps hash-chained
evidence, and turns recorded decisions into CI regression tests. This release
makes it usable in a real developer workflow.

## Highlights

- **`atp mcp-proxy`** — a stdio MCP proxy in front of an existing MCP server.
  Every `tools/call` is authenticated, decided against delegated authority
  (including argument-derived resources), released under a single-use grant,
  forwarded, and its outcome recorded. Verified against the in-repo notes
  server and the reference `@modelcontextprotocol/server-filesystem`.
- **`atp` CLI** — `doctor`, `demo injection|regression|mcp`, `test`, `record`,
  `serve`, `keygen`, `mcp-proxy`, `mcp-init`.
- **Security regression suites** — YAML cases pinning `outcome`/`reason_code`/
  `matched_policy`; `atp test` runs them on an ephemeral gateway with no side
  effects and emits JSON + JUnit; `atp record` converts a trace into a case
  deterministically (no LLM). GitHub Actions example included.
- **Dashboard before/after** — the same recorded action under two policy
  sets, with the policy diff, the delegated authority, the side effect that
  replay cannot undo, and what replay is and is not.
- **Benchmark** — policy evaluation 0.3 ms; authorize+execute ~11 ms p50 on
  loopback; ~21 ms p50 added to an MCP tool call end to end. Method and
  limits in `docs/benchmarks.md`.
- **Research** — `docs/competitive-landscape.md` (ContextForge, agentgateway,
  ToolHive, Docker MCP Gateway, mcp-gate, promptfoo, Inspect, AgentDojo) and
  the product-wedge decision in ADR-0002.

## Quickstart

```
git clone <repo> && cd agent-trust-plane
uv sync
uv run atp demo mcp
```

Measured 51 s from a cold clone to the first result on the reference machine.

## Verification

334 tests (gateway tests on in-memory and SQLite stores), 8/8 adversarial
evals, ruff, mypy `--strict`, dashboard typecheck + production build, three
demos and the sample regression suite all run in CI on Python 3.12 and 3.13.

## Known limitations

Operator key is omnipotent; agent credentials are bearer tokens; an agent
that can reach an upstream directly bypasses the proxy; stdio only; one
upstream per proxy; no approval workflow; no rate limits; single gateway
instance; local ledger only. See `docs/security-review.md` (open findings)
and `docs/deployment.md`.

## Breaking changes from 0.1.0

- `/health` no longer returns `signing_key_fingerprint`; `tools` includes
  external prefixes.
- `POST /traces/{id}/events` no longer accepts `actor` (set from the credential).
- Reads (`/traces*`, `/ledger/payments`, `/delegations*`, `/replay`) require
  the operator key.
