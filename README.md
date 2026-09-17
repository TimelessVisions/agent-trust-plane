# Agent Trust Plane

**Put a real authorization boundary between your AI agent and its tools, and turn every dangerous action into a regression test so it cannot silently come back.**

![Real transcript of `atp demo wrap`: a write is allowed, a delete is denied before it reaches the server, the denial is explained, pinned as a regression test, and the test passes](https://raw.githubusercontent.com/TimelessVisions/agent-trust-plane/main/docs/images/demo-wrap.svg)

```bash
uv run atp demo wrap                        # a real MCP server, wrapped; one ALLOW, one DENY, one regression test
uv run atp mcp init -- <your mcp server>    # then: atp mcp wrap   (Streamable HTTP upstreams: --url)
uv run atp regression add <trace> && uv run atp test atp-regression.yaml
```

> **Status: experimental, v0.3.2, no users yet, not independently audited.** Every claim below is backed by a test in this repository or says otherwise. What it does *not* protect is in [docs/security/threat-model.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/security/threat-model.md).

## Why this exists

Agents act on tool calls, and the tool call is where prompt injection turns into damage: pay this account, delete that file, move this repo. Gateways in front of MCP servers authenticate the caller and allow tools by *name*; most cannot decide on the *arguments* (amount, path, destination) and none replay a recorded decision or keep it fixed in CI ([research, with citations](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/research/competitive-code-review.md)). ATP does that part and only that part: it is a decision-and-evidence layer, not a gateway ([why-atp.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/why-atp.md)).

## How it works

```
agent / MCP client ──stdio──▶ atp mcp wrap ──▶ upstream MCP server (stdio or Streamable HTTP)
                                   │
                    authenticate the agent; resolve HUMAN → agent delegation (capabilities,
                    resource scope, limits — a child can only narrow)
                    build an ActionEnvelope from the call (paths normalised, args bounded)
                    decide: kernel policies + your declared policy set   →  ALLOW / DENY / WOULD_DENY
                    ALLOW  → single-use grant over the exact action hash → forward → record outcome
                    DENY   → refuse (enforce)  |  forward and record WOULD_DENY (shadow)
                    everything on a hash-chained trace in .atp/
```

Then, offline: `atp trace list` · `atp policy explain TRACE` · `atp regression add TRACE` · `atp test` · `atp policy impact --from A --to B` · `atp mutate TRACE` · `atp evidence export TRACE`.

## Quickstart (measured: [docs/first-user-test-v2.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/first-user-test-v2.md))

Prerequisites: Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/). No API keys, no Docker, no database setup, no secrets to copy.

```bash
git clone <this repository> && cd agent-trust-plane
uv run atp demo wrap          # syncs the workspace on first run; 37 s cold on the maintainer machine
```

The same commands work in PowerShell. `uv run atp doctor` explains anything missing. Other demos: `atp demo injection` (an injected invoice tries to pay $12,500 on a $1,000 delegation), `atp demo regression` (a permitted payment reveals a policy hole; replay under the fix flips it), `atp demo mcp` (the proxy against a remote-style gateway) — [docs/demos.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/demos.md).

## Wrap your own MCP server

```bash
uv run atp mcp init --name fs -- npx -y @modelcontextprotocol/server-filesystem /abs/sandbox
#   reads tools/list; proposes capabilities from the server's annotations (unverified: review them);
#   writes atp-mcp.yaml and .atp/policies.yaml (declared set fs-v1)
uv run atp mcp wrap --mode shadow      # observe first: denials are recorded as WOULD_DENY and forwarded
uv run atp mcp wrap                    # enforce
```

Tools the server itself marks destructive (`write_file`, `edit_file`, `move_file` on the reference server) get `fs:destroy`, which is **not delegated by default**: the first write is denied with `CAPABILITY_NOT_GRANTED` until you add `fs:destroy` to `authority.capabilities` in `atp-mcp.yaml` — a deliberate fail-closed default, and the one thing the first-user test tripped over.

Point your MCP client at the wrap command instead of the server ([config example](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/integrations/frameworks.md)). Verified upstreams: this repo's notes server (stdio and Streamable HTTP, every CI run) and the reference `@modelcontextprotocol/server-filesystem` (opt-in test, run 2026-09-17). Everything else is listed as *not verified* in [docs/integrations/compatibility.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/integrations/compatibility.md).

Scope paths, not just tool names: `resource_scope: ["path:/abs/sandbox/*"]` with `..`, separators and (optionally) case normalised before matching. Argument limits go in [`.atp/policies.yaml`](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/policies/policies.md):

```yaml
rules:
  - id: no-large-writes
    applies_to: {tool: mcp.fs, action: write_file}
    kind: argument_max_length
    argument: content
    max_length: 20000
```

## Security regression tests

```bash
uv run atp trace list                                   # what was ALLOWed / DENIED / WOULD_DENY
uv run atp policy explain 457328bdd4ef                  # which constraint failed, and what would need to change
uv run atp regression add 457328bdd4ef --name "delete stays denied"
uv run atp test atp-regression.yaml                     # exit 1 if the decision ever changes; --junit/--json for CI
uv run atp policy impact --from fs-v1 --to fs-v2        # which recorded actions flip; DENY -> ALLOW first
uv run atp mutate 457328bdd4ef                          # perturb the recorded action; authorize only, never execute
```

A suite is YAML: principals, a delegation graph, cases with the expected outcome / reason / policy. Runs use an ephemeral in-process gateway and call only `/authorize` — a spy on `execute` sees zero calls. CI example without secrets: [examples/regression-suite](https://github.com/TimelessVisions/agent-trust-plane/tree/main/examples/regression-suite/) and a copy-in [composite action](https://github.com/TimelessVisions/agent-trust-plane/tree/main/examples/github-action/). Guide: [docs/regression/regression-testing.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/regression/regression-testing.md).

## Architecture

Protocol-neutral kernel (`atp_core` envelope/decision, `atp_identity` credentials + delegation chains, `atp_policy` engine + declared sets, `atp_audit` hash chain, `atp_gateway` service/grants/API) with adapters on the edge (`atp_adapter_mcp` proxy, `atp_adapter_http` client) and the `atp` CLI. One distribution, `agent-trust-plane`, installs everything (`uvx --from <wheel-or-git-url> atp …`). The kernel imports nothing from MCP — a test enforces it. Details: [docs/architecture/architecture.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/architecture/architecture.md), [first principles](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/architecture/first-principles.md), [ADRs](https://github.com/TimelessVisions/agent-trust-plane/tree/main/docs/adr/).

Overhead ([docs/benchmarks.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/benchmarks.md), single machine, sequential): policy engine 0.26 ms; `atp mcp wrap` adds ~11 ms p50 to an MCP tool call with durable SQLite evidence; the HTTP-gateway proxy path adds ~21 ms.

## Security model and limitations

Guarantees, assumptions, deployment requirements, non-guarantees and known gaps are separated in [docs/security/threat-model.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/security/threat-model.md); attempted attacks and results in [docs/red-team/architecture-attacks.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/red-team/architecture-attacks.md); the self-review with severities in [docs/security/security-review.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/security/security-review.md). Headlines:

- **Only the mediated path is protected.** An agent that can reach the tool without the proxy is not stopped — a test shows it on purpose. Whether that can happen is a deployment property: [docs/security/enforcing-the-boundary.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/security/enforcing-the-boundary.md).
- **The operator (and `.atp/keys.env`) is omnipotent**; agent credentials are bearer tokens with expiry and revocation, no proof of possession.
- **Single-use grants prove one release, not exactly-once external effects**: [docs/security/idempotency.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/security/idempotency.md).
- The hash chain catches edits by non-writers; a DB writer can recompute it: [docs/security/trace-integrity.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/security/trace-integrity.md).
- Declared policies are limit/equality rules; use OPA/Cedar for more ([why-not-just-opa.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/policies/why-not-just-opa.md)). Prompt injection is bounded, not detected.

Evidence for what *is* handled: 439 tests including property-based tests (delegation monotonicity, scope-algebra soundness, a stateful grant lifecycle with tampering and revocation interleaved), an exhaustive check of the grant state machine ([spec](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/formal/grant-lifecycle.md)), eight adversarial evals, and real-protocol MCP end-to-end tests.

## Contributing

[CONTRIBUTING.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/CONTRIBUTING.md), [DEVELOPMENT.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/DEVELOPMENT.md) (module map, invariants not to break, how to add a policy or adapter), [ROADMAP.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/ROADMAP.md), [docs/good-first-issues.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/good-first-issues.md), [SECURITY.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/SECURITY.md) for reporting a vulnerability, [CHANGELOG.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/CHANGELOG.md). [MIT licensed](https://github.com/TimelessVisions/agent-trust-plane/blob/main/LICENSE) (dependency and copyright record: [docs/release/licensing.md](https://github.com/TimelessVisions/agent-trust-plane/blob/main/docs/release/licensing.md)). No telemetry.
