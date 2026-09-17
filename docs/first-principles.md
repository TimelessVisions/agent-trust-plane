# First principles

Written before designing features for v0.3.0, starting from what a
consequential agent action *is*, not from what the code already does.

## What is an agent action?

A consequential action is a request that, if executed, changes something
outside the agent's own reasoning. Its minimum representation separates
what is *claimed* from what is *resolved* from what *happened*:

| Part | Claimed by | Resolved / decided by | Recorded as |
|---|---|---|---|
| actor | the caller (an id in the envelope) | the gateway, from an authenticated credential | `authenticated_agent` on the first trace event |
| authority source | the caller names a human principal | the gateway checks the chain root is that human | `delegation_resolved.authority.root_principal` |
| delegation | the caller names a grant id | the gateway resolves the chain, checks the leaf is the actor | `delegation_resolved.chain` |
| intent | the caller (`capability`, e.g. `pay:vendor`) | must be held by the effective authority | envelope |
| target | the caller (`resource`) | must be inside the effective scope | envelope |
| operation | the caller (`tool`, `action`) | must map to a registered or external tool | envelope |
| arguments | the caller (bounded JSON) | evaluated by argument-aware policies | envelope (hashed) |
| context | the caller (provenance: task, content sources, rationale) | never trusted; kept for review | envelope.provenance |
| constraints | nobody claims them | computed: chain intersection | `effective_authority.constraints` |
| policy | nobody chooses them (operator override only) | the gateway's default policy set | `decision.policy_set_version` |
| authorization decision | — | the policy engine, deterministically | `decision_made` |
| execution grant | — | minted only on ALLOW; binds `action_hash` + audience + expiry | `grant_issued` |
| execution | the holder presents the grant | the gateway verifies, consumes once, runs or releases | `execution_*` |
| result | the tool or the external executor | recorded, bounded, never trusted | `execution_completed.result` / `summary` |
| side effect | the tool | outside the gateway; only its *report* is recorded | ledger row / executor outcome |
| evidence | — | the hash-chained trace | the trace |

The `ActionEnvelope` already separates these; what it must never do is
carry a decision, a mode, or a policy choice.

## What must be trusted

| Anchor | Why | Consequence of compromise |
|---|---|---|
| The gateway process and its store | It resolves authority, decides, mints grants, writes evidence | Total: a DB writer can forge everything (`security-review.md` O4) |
| The operator key | Issues credentials, roots delegations, overrides policy, reads evidence | Total (O1) |
| Grant signing key | Grants are HMAC | Forged grants; single-use store still limits to recorded grant ids |
| Policy source | Policy sets are code or a YAML file loaded at start | Wrong policy = wrong decisions, but recorded under that policy version |
| The executor of external tools (the MCP proxy) | It holds the upstream and a bearer token | Can forward what it likes to *its* upstream; cannot mint grants or forge decisions (O14) |
| Deployment boundary | Tools must be reachable only via the gateway/proxy | Bypass (O3/O13) |
| Clock | Expiry checks | Skew widens windows (O12) |

## What must not be trusted

LLM output; prompts; retrieved documents; tool descriptions and
annotations (MCP spec: "clients MUST consider tool annotations to be
untrusted unless they come from trusted servers"); tool results; MCP
metadata; traces imported from elsewhere; every field of the envelope that
is not re-derived server-side; a requested policy version; a requested
mode; arbitrary JSON sizes; the agent's stated rationale.

Concretely, in this release: the mapping generator reads annotations to
*propose* a config that a human commits; the regression recorder treats
the trace as hostile input; shadow mode is a gateway setting the caller
cannot request; the proxy refuses oversized arguments instead of
truncating.

## The central invariant

> **No side effect may occur unless the exact side effect was authorized
> for the authenticated actor under valid delegated authority — and every
> such authorization is recorded before the side effect.**

Decomposed into testable properties (`packages/*/tests/test_properties.py`
and the state machine in `docs/formal/grant-lifecycle.md`):

1. *Authority monotonicity*: effective authority ⊆ every ancestor's.
2. *Identity binding*: credential subject = envelope agent = chain leaf =
   grant audience.
3. *Execution exactness*: executed action hash = authorized action hash.
4. *Single use*: at most one consumption per grant.
5. *Revocation*: no consumption after effective revocation of credential
   or any chain link.
6. *Determinism*: same envelope + authority snapshot + policy set ⇒ same
   outcome, reason and matched policy.
7. *Replay safety*: replay never mints a grant or calls a tool.
8. *Fail closed*: unknown tool, unmapped MCP tool, missing policy set,
   missing grant, malformed input ⇒ no execution.
9. *Evidence precedence*: `decision_made` precedes any `execution_*` on the
   same trace.

Is this truly central? Yes, with one honest qualification: ATP can
guarantee "no *gateway-mediated* side effect"; it cannot guarantee "no
side effect" when the tool is reachable without it. That is why the
boundary document (`docs/security/enforcing-the-boundary.md`) is part of
the security model, not an appendix.

## What should be model-agnostic

Everything. No module imports a model SDK except the optional demo agent.
The kernel sees an envelope and a credential; it does not know whether a
model, a script or a human produced them.

## What should be protocol-agnostic

The kernel (`atp_core`, `atp_identity`, `atp_policy`, `atp_audit`,
`atp_gateway.service`). Adapters own protocol behaviour: `atp_adapter_mcp`
turns MCP `tools/call` into envelopes and MCP results; `atp_adapter_http`
is the wire client. An A2A adapter or an OpenAI-Agents guardrail would be
another 200-line adapter, not a kernel change.

## What should be deterministic

The decision path. Policies are pure functions of (envelope, authority
snapshot, vendor directory, clock). No network, no model, no randomness.
`Decision.evaluations` records every comparison so the same inputs can be
checked by hand.

## What should be replayable, and what must not be

| Kind | Meaning | ATP |
|---|---|---|
| Authorization replay | Re-evaluate the recorded envelope against the recorded authority under a policy set | ✅ `/replay`, `atp policy impact` |
| Policy replay | Same, across a whole set of recorded actions | ✅ impact analysis |
| Trace replay | Re-emit the events | Not needed; traces are immutable |
| Agent rerun | Run the model again | ✗ never; nothing in ATP calls a model |
| Side-effect replay | Execute again | ✗ impossible by construction: replay mints no grant; `execute` needs a grant; grants are single-use |

## What should be portable

Policy sets (YAML), regression suites (YAML, versioned), evidence bundles
(JSON with deterministic hash), decision explanations (JSON/text). All
four are files a reviewer can move between machines.

## What is the fundamental product?

Of the candidates (gateway, authorization server, policy engine, MCP
proxy, regression framework, action firewall, capability system,
evidence/replay platform), ATP is a **combination of three**:

- a **capability system** for agent actions (delegated, attenuating
  authority; execution grants bound to exact actions);
- an **evidence/replay platform** (hash-chained decisions you can
  re-evaluate);
- a **security regression framework** (recorded decisions become CI tests,
  impact and mutation analysis run offline).

It is *not* a gateway (no hosting, isolation, transports served) and *not*
a policy engine in the OPA/Cedar sense (its policy language is deliberately
small and its policy boundary is designed to host those engines later).
The MCP proxy is the delivery vehicle for the first two, not the product.
