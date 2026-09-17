# Launch post (technical, ~400 words) — draft, not published

**Agent Trust Plane v0.2: intercept an MCP tool call, decide it against
delegated authority, prove the fix, keep it fixed in CI.**

Most MCP gateways can say "this agent may call `write_file`". Few can say
"this agent may write *this* file, for *this* human, up to *this* limit" —
agentgateway's authorization rules cannot see tool arguments at decision time
(their issue #2069), ToolHive's Cedar sees scalar arguments, Docker's gateway
leaves argument policy to custom interceptors. And none of them replay a
recorded decision under a changed policy or turn it into a regression test.
That's the gap this release is aimed at.

What ships:

- `atp mcp-proxy`: a stdio proxy in front of any stdio MCP server. Each
  `tools/call` becomes an envelope (agent, human principal, delegation grant,
  capability, argument-derived resource, arguments). The gateway authenticates
  the agent, intersects its delegation chain down to effective authority,
  evaluates versioned policies, and on ALLOW mints a single-use grant over the
  exact action hash. Only then is the call forwarded; the outcome is reported
  back against the consumed grant. Unmapped tools are denied and hidden.
- `atp test`: YAML suites that pin outcome, reason code and matched policy for
  a delegation graph and a set of actions. They run on an ephemeral gateway,
  call only `/authorize`, and exit non-zero when a decision changes. JUnit and
  JSON out; a no-secrets GitHub Actions example.
- `atp record`: deterministic trace → case conversion. No LLM anywhere.
- A dashboard panel that shows the same recorded action before and after a
  policy change, the diff, and the side effect that replay cannot undo.

What it proved on my machine (cold clone → working proxy demo: 51 s):
`write_note` allowed and executed, `delete_note` denied and never reaching
the server, a `write_note` to a note outside the delegated scope denied —
over the real protocol, against the reference filesystem server too.
Overhead: ~21 ms p50 added to an MCP tool call, ~11 ms of which is the two
loopback round trips to the gateway.

What it does not do, so you don't have to find out: the operator key is
omnipotent; agent credentials are bearer tokens; an agent that can launch the
upstream itself bypasses the proxy (a test demonstrates it); stdio only, one
upstream per proxy; no approval workflow; no rate limits; the "payments" are a
SQLite table. All listed with severities in `docs/security-review.md`.

328 tests (+1 opt-in third-party test), 8 adversarial evals, strict typing, MIT. If you run agents against
tools that matter and want to compare notes on where the boundary should
sit, the repo link is in the first comment.
