# Why not just OPA (or Cedar)?

Short answer: you can, for the part that is a policy question. ATP does not
compete with Open Policy Agent or Cedar as policy languages and its own
declared format is deliberately tiny. What ATP provides is the agent-
specific control loop around the policy question, which neither engine
provides or claims to.

## What OPA and Cedar do well

- A real language (Rego, Cedar) with tooling: unit tests (`opa test`,
  Cedar's validator), coverage, formal analysis (Cedar), bundles, decision
  logs.
- Mature evaluators, large communities, Kubernetes/Envoy integrations.
- Expressiveness ATP's eight rule kinds will never match.

If your policies are complex, write them in Rego or Cedar. ATP's policy
boundary (`atp_policy.base.Policy`: `applies_to(ctx)` and `evaluate(ctx)`
returning a typed evaluation with named constraints) is where an adapter
plugs in; the engine does not know policy classes. An OPA adapter would
post the envelope + effective authority as `input` and map the result to
`PolicyEvaluation`; a Cedar adapter would map principal = agent, action =
`tool.action`, resource = resource, context = arguments + authority. Neither
is built yet (`../research/rejected-ideas.md`, "OPA adapter now").

## What a policy engine does not give an agent

A PDP answers "given this input, allow or deny?" It does not:

1. **Establish who is asking.** ATP authenticates the agent and refuses an
   envelope whose `agent` differs from the credential subject.
2. **Compute authority from delegation.** "Agent B may spend up to $1,000
   because human A delegated $10,000 to orchestrator O which delegated
   $1,000 to B" is data ATP resolves and intersects before any policy runs;
   in OPA you would have to model the chain yourself and keep it in sync.
3. **Bind the decision to execution.** An `allow` from a PDP is advice. ATP
   mints a single-use grant over the exact action hash and refuses to
   execute anything else; the tool call cannot drift from what was decided.
4. **Intercept tool calls without code changes.** `atp mcp wrap` sits in
   front of an MCP server; a PDP has no transport.
5. **Record evidence you can replay.** Every decision, with every
   constraint value, is on a hash-chained trace; `atp policy impact` re-
   decides recorded actions under another version; `atp regression add`
   pins one as a CI test.
6. **Fail closed on unknown actions.** Unmapped tools are denied and hidden
   by default.

OPA's decision logs and Cedar's analysis address parts of 5 at the policy
level (which policies changed), not at the action level (which recorded
calls flip). Both are complementary: ATP could ship its recorded actions to
`opa test` or use Cedar's analysis to check a declared set. Neither
replaces the loop.

## When to use which

| You want | Use |
|---|---|
| Rich policy language over your own domain model | OPA / Cedar |
| Argument-aware limits derived from human delegation, with a bound execution | ATP (with built-in or declared rules) |
| Both | ATP with a policy-engine adapter (roadmap) |
| Policy-level analysis ("does v2 permit more than v1?") | Cedar analysis (`atp policy diff` is structural only) |
| Action-level analysis ("which recorded calls flip?") | `atp policy impact` |

## Honest gaps

- ATP's declared rules are equality/limit checks; anything conditional on
  two arguments at once, or on time, needs a real engine.
- No adapter exists today; the boundary is designed and the rejected-ideas
  note says why it was not built in this pass.
- If you already run OPA everywhere, the thing to adopt from ATP first is
  the evidence + regression loop, not the policy format.
