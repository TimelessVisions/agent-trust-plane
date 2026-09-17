# Agent-to-agent delegation and ATP's model (research note, 2026-09-17)

## What exists

- **A2A** (Agent2Agent) reached v1.0 in April 2026 under the Linux
  Foundation, with a 1.0.1 extension mechanism in May 2026 and adoption
  claims of 150+ organisations. It standardises how one agent discovers
  another (agent cards), sends tasks, streams status and exchanges
  artifacts. Authentication is per agent endpoint (OAuth/OIDC/API keys per
  the card); there is no notion of *bounded, attenuating authority* passed
  with a task.
- "Governance Gaps in Agent Interoperability Protocols: What MCP, A2A, and
  ACP Cannot Express" (arXiv 2606.31498) argues exactly that gap.
- MCP itself is tool-oriented; sub-agents are typically spawned by the
  same runtime (LangGraph subgraphs, OpenAI Agents handoffs) with the
  parent's full credentials.

## What ATP already models

The delegation kernel is protocol-neutral and already chains agents:

```
human (root, self-issued) → orchestrator agent → worker agent → tool
```

Each link may only narrow: capabilities ⊆ parent, scope covered by parent,
`max_amount` ≤ parent, currencies ⊆ parent, expiry ≤ parent. Resolution
intersects the whole chain, and the leaf must be the authenticated caller.
This is what an A2A task needs and does not have: "orchestrator delegates
to worker *a bounded slice* of what the human gave it".

## How an A2A adapter would map (not built)

| A2A concept | ATP concept |
|---|---|
| Client agent sends a task to a remote agent | Client agent (grantee of grant G) issues a *child* delegation G' to the remote agent's principal id, narrowed to the task (`POST /delegations` authenticated as the client agent) |
| Task message | carries `delegation_grant_id = G'` (in metadata; A2A allows arbitrary metadata) |
| Remote agent calls a tool | builds an `ActionEnvelope` under G' through its own ATP proxy; the gateway resolves the full chain back to the human |
| Task completion | `revoke G'` (or let it expire with the task) |
| Agent identity | the remote agent needs a credential the gateway accepts: today a bearer issued by the operator; later a workload identity (`identity-providers.md`) |

Nothing in the kernel changes. The adapter is ~200 lines: issue narrowed
grant, attach id to task metadata, revoke on completion. The hard part is
cross-organisation identity (two gateways, two operators), which is a
federation problem ATP does not solve.

## What must be true before building it

1. A real A2A deployment that wants bounded delegation (none has asked).
2. Workload identity for remote agents (SPIFFE/OIDC provider).
3. A story for two gateways: either one gateway both agents trust, or
   grant chains that cross gateways with signed links (Biscuit-style),
   which is a new trust model.

## Decision

Design documented; no code. The kernel's chain model is the asset; an
A2A binding is an adapter when demand appears.
