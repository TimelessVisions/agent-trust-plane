# ADR-0001: Control-plane architecture for bounded agent authority

Status: Accepted
Date: 2026-09-16

## Context

Autonomous agents are being wired to tools that move money, mutate records,
and delegate work to other agents. The model that proposes an action is also
the component most exposed to untrusted input (documents, web pages, tool
output). A system that lets the proposer decide whether its own proposal
executes has no control boundary.

Agent Trust Plane places an independent enforcement layer between the agent
and the tool. This ADR records the shape of that layer for the MVP and the
tradeoffs accepted to keep it finishable.

## Decisions

### D1. Models propose, infrastructure decides

Every consequential tool call is expressed as an `ActionEnvelope` and sent to
the gateway. The gateway alone resolves authority, evaluates policy, and
decides `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`. Agent code never receives a
"you are authorized" flag it can forward; it receives a signed, single-use
execution grant or nothing.

### D2. The envelope references authority; it does not assert it

The spec sketch carried an `authorization` block inside the envelope
(`max_amount`, `scope`, `expires_at`). We deliberately do not do that. A
client-supplied authorization claim is untrusted by definition. The envelope
carries a `delegation_grant_id`; the gateway resolves the grant chain from its
own store and computes effective authority as the **intersection** of every
grant on the path to the human root.

### D3. Delegation is a chain of grants with intersection semantics

A `DelegationGrant` names a grantor, a grantee, a parent grant, capabilities,
a resource scope, constraints (monetary limit, currency allowlist), and an
expiry. Two enforcement points uphold "a child never has more authority than
its parent":

1. **At issuance** — the identity package rejects any grant that exceeds its
   parent (capabilities, resource scope, monetary limit, expiry).
2. **At resolution** — the gateway recomputes effective authority as the
   chain-wise intersection, so a tampered or inconsistent stored grant still
   cannot widen authority.

### D4. Policies are structured objects evaluated by an engine

Each policy has a stable id + version (`payments.vendor.max_amount.v1`), a
`applies_to` predicate, and an `evaluate` method returning a typed result with
a reason code and the constraints it looked at. A `PolicySet` is a versioned,
ordered list. The engine evaluates **every applicable policy** (no short
circuit) so the trace shows all violations, then reduces: any `DENY` wins,
else any `REQUIRE_APPROVAL`, else `ALLOW`. The first denying policy is the
"matched policy" reported in the decision.

Policy sets are versioned so replay can rerun a historical action against a
different policy version.

### D5. Authorization is bound to execution with a signed, single-use grant

`/execute` cannot be reached by simply claiming `authorized: true`. It
requires an **execution grant** minted by `/authorize` on `ALLOW`:

- Payload: `grant_id`, `trace_id`, `decision_id`, `envelope_hash`
  (SHA-256 of the canonical JSON of the action-defining envelope fields),
  `policy_set_version`, `issued_at`, `expires_at` (short TTL, default 120 s).
- Signature: HMAC-SHA256 over the canonical payload using a server-side key.
- Server-side record: `status ∈ {issued, consumed, expired, revoked}`.

At `/execute` the gateway verifies, in order: signature (constant-time),
expiry, envelope hash equality against the envelope actually submitted,
server-side existence, and then **atomically** transitions the record from
`issued` to `consumed` (`UPDATE ... WHERE status='issued'`, rowcount must be
1). Only then does the tool run. Any failure records an
`execution_blocked` event with a specific reason code.

**Why HMAC and not an asymmetric signature.** In the MVP the authorizer and
the executor are the same process, so a shared secret is sufficient and avoids
key distribution. The token format is versioned (`atp-grant/1`) so it can be
switched to Ed25519 when executors run as separate services. The server-side
record is what gives single-use and revocation; the signature is what gives
tamper-evidence and lets the hash mismatch be detected before touching the
database.

**Why both a signature and server-side state.** State alone (opaque random
ids) would bind execution, but the client could not tell what it holds and an
executor service could not verify anything without a database round trip.
Signature alone cannot provide single-use. Together they are cheap and cover
forgery, tampering, replay, and expiry.

### D6. Audit is an application-enforced, hash-chained, append-only log

Every trace event carries `prev_hash` and `hash = sha256(prev_hash ||
canonical(event))`. The store exposes append and read only. `GET /traces/{id}`
recomputes the chain and reports `integrity.valid`. This is tamper-*evident*
against accidental or naive mutation, not tamper-*proof* against an attacker
with database write access (they can rewrite the chain). ADR notes what
production would need: external anchoring of chain heads, write-only
credentials, and a separate audit sink.

### D7. Replay reruns authorization, never execution

`POST /replay/{trace_id}` loads the original envelope and the delegation
chain **snapshot** recorded at authorization time, evaluates it under the
requested policy set version, and records a `replay_performed` event on the
original trace plus a diff between the original and replayed decisions.
Replay does not mint grants and cannot execute.

### D8. The agent in the demo is simulated by default

The demo ships a deterministic `SimulatedAgent` that behaves like a naive
LLM: it follows instructions found in retrieved content. This keeps evals
reproducible and free of API keys. An optional `AnthropicAgent` can be
switched on with an API key and exercises the same envelope path. The control
plane is model-agnostic by construction; the model is not the interesting
part.

### D9. Persistence is SQLite via the standard library

No ORM, no Postgres, no Redis. Each store (`grants`, `delegations`,
`trace_events`, `payments`, `eval_runs`) is behind a small interface so a
different backend can be swapped in without touching policy or gateway logic.

### D10. Monorepo as a `uv` workspace

Python packages are separately installable distributions (`atp-core`,
`atp-identity`, `atp-policy`, `atp-audit`, `atp-evals`, `atp-gateway`,
`atp-adapter-http`, `atp-adapter-mcp`, `finance-agent`) with explicit
dependency direction:

```
core ← identity ← policy ← audit? (no: audit depends only on core)
core ← audit
policy, identity, audit ← gateway ← evals, adapters, examples
```

`packages/core` is an addition to the requested layout. It holds the shared
domain models (envelope, decision, reason codes, money, principals) so
identity, policy, and audit do not import each other.

## Consequences

- Anything the agent asserts about its own authority is ignored. The only
  input that matters is the grant id and the gateway's own records.
- Every decision is explainable by reason code, matched policy, and the
  constraints evaluated, and every decision is reproducible by replay.
- The MVP's security boundary is the gateway process and its SQLite file.
  Compromise of either defeats the guarantees; the threat model says so.
