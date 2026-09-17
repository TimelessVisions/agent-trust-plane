# Why ATP, when MCP gateways exist?

Compare workflows, not feature lists. All gateway claims below are cited
in [research/competitive-code-review.md](research/competitive-code-review.md)
(inspected 2026-09-17).

## The workflow an MCP gateway gives you

```
agent ──▶ gateway ──▶ MCP server
            │
            ├─ authenticate the caller (JWT/OIDC/API key)
            ├─ allow/deny the tool by NAME (CEL, Cedar, enable lists)
            ├─ isolate the server (containers), scope its secrets
            └─ log the call (name; argument shape; sometimes values)
```

What you learn when something goes wrong: "agent X called tool Y at
time T". What you cannot do: decide on the *amount*, the *destination*,
the *path* (agentgateway cannot see arguments at decision time; ToolHive
sees scalars against literals; Docker logs argument shape only); prove
afterwards what the decision was based on; re-run that decision under a
fixed policy; or make CI fail if the fix regresses.

## The workflow ATP gives you

```
agent ──▶ atp mcp wrap ──▶ MCP server          (stdio or Streamable HTTP upstream)
              │
              ├─ 1. authenticate the agent; resolve HUMAN → … → agent delegation
              ├─ 2. build an ActionEnvelope: capability, resource (from the arguments,
              │     paths normalised), bounded arguments, provenance
              ├─ 3. decide: kernel policies (delegation, capability, scope) +
              │     the policy set (argument limits, payments rules)
              ├─ 4. ALLOW → single-use grant over the exact action hash → forward;
              │     DENY → refuse (or, in shadow mode, forward and record WOULD_DENY)
              ├─ 5. record every step on a hash-chained trace, including what came back
              │
              └─ later, offline, from .atp/:
                    atp policy explain TRACE     why / what would need to change
                    atp regression add TRACE     pin the decision as a CI test
                    atp test suite.yaml          exit 1 if it ever flips
                    atp policy impact A B        what a policy change does to recorded actions
                    atp mutate TRACE             probe for holes around a recorded action
                    atp evidence export TRACE    hash-checked bundle for a reviewer
```

## Side by side, on one incident

An agent processing an invoice is told (by the invoice) to pay $12,500 to
a new account. Its human delegated $1,000.

| Step | Gateway | ATP |
|---|---|---|
| Decide | tool `send_payment` is allowed for this agent → forwarded | amount 12,500 > delegated 1,000 → `DENY PAYMENT_EXCEEDS_DELEGATED_AUTHORITY`; no grant; nothing forwarded |
| Explain | log line | every constraint with its values; "reduce to ≤ 1,000 or raise `max_amount` on grant `grt_…` and below" |
| Prove the fix | re-deploy, hope | `atp policy impact --from v1 --to v2`: this recorded call flips ALLOW → DENY, nothing else does |
| Keep it fixed | — | `atp regression add`; CI exits 1 if the decision ever changes |
| Hand to a reviewer | log export | evidence bundle with a verifiable chain |

## What ATP does not do (use a gateway for these)

Host or isolate servers; manage upstream secrets; serve Streamable HTTP
with client auth; federate; OTel. ATP sits *beside* those: today as a
local proxy, later as an interceptor/ext-authz inside them (roadmap).

## What to be sceptical about

- Only the gateway-mediated path is protected; an agent that reaches the
  server directly is not ([security/enforcing-the-boundary.md](security/enforcing-the-boundary.md)).
- The policy language is small on purpose ([policies/why-not-just-opa.md](policies/why-not-just-opa.md)).
- No production users; experimental; not independently audited.
