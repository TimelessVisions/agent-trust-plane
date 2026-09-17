# Feature matrix (as of 2026-09-17)

Legend: ✅ present and documented/verified · ◐ partial · ✗ absent · ? not
determined from docs/code. "ATP" reflects the tree after this pass; items
marked *new* were added in v0.3.0. Sources: `competitive-code-review.md`.

| Capability | ATP | agentgateway | ToolHive | Docker MCP GW | ContextForge | mcp-airlock | promptfoo | Inspect AI |
|---|---|---|---|---|---|---|---|---|
| Runs / hosts MCP servers | ✗ | ✅ | ✅ (containers) | ✅ (containers) | ✅ | ✗ (proxy) | ✗ | ✗ (sandboxes for evals) |
| MCP stdio | ✅ proxy | ✅ | ✅ | ✅ | ✅ | ✗ | n/a | n/a |
| MCP Streamable HTTP (serve) | ✗ (roadmap) | ✅ | ✅ | ✅ | ✅ | ✅ | n/a | n/a |
| MCP Streamable HTTP (upstream) | ◐ *new* (client side) | ✅ | ✅ | ✅ | ✅ | ✅ | n/a | n/a |
| Tool allow/deny by name | ✅ (unmapped = deny) | ✅ CEL | ✅ Cedar | ✅ | ◐ (#4647 open) | ✅ tiers | ✗ | ✅ approval |
| Decision on argument *values* | ✅ | ✗ (#2069) | ◐ scalars only | ◐ custom interceptor | ✗ (#6408) | ◐ count_arg | n/a | ◐ prefix match |
| Authority derived from delegation chain (human → agent → agent), attenuating | ✅ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Per-agent authenticated identity | ✅ bearer | ✅ JWT/OAuth | ✅ OIDC | ◐ | ✅ | ✅ JWT | n/a | n/a |
| Decision bound to execution (single-use, hash-bound grant) | ✅ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Tamper-evident record of calls with argument values | ✅ hash chain (naive edits) | ✗ logs | ✗ logs | ✗ (shape only; #557 open) | ✗ (OTel) | ◐ audit log | ✗ | ✗ |
| Replay recorded decision under another policy | ✅ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Recorded call → regression test | ✅ `atp regression add` *new* | ✗ | ✗ | ✗ | ✗ | ✗ | ◐ (scenario gen) | ✗ |
| CI runner with exit codes / JUnit | ✅ | ✗ | ✗ | ✗ | ✗ | ✗ | ✅ | ✅ |
| Policy explain (why + what would need to change) | ✅ *new* | ✗ | ◐ Cedar diagnostics | ✗ | ✗ | ✗ | n/a | n/a |
| Policy impact over recorded actions | ✅ *new* | ✗ | ✗ (policy-level analysis exists in Cedar) | ✗ | ✗ | ✗ | ✗ | ✗ |
| Offline request mutation against policy | ✅ *new* | ✗ | ✗ | ✗ | ✗ | ✗ | ◐ red-team plugins (model-side) | ✗ |
| Shadow / observe mode | ✅ *new* (gateway-declared) | ◐ (log-only routes) | ✗ | ✗ | ? | ✅ (log tiers) | n/a | n/a |
| Declarative policy sets | ✅ *new* (small YAML) | ✅ CEL | ✅ Cedar | ✗ | ◐ | ✅ YAML | n/a | ✅ |
| Human approval workflow | ✗ (recorded only) | ✗ | ✗ | ✗ | ? | ✅ | ✗ | ✅ |
| Secrets / credential isolation for tools | ✗ | ✅ | ✅ | ✅ | ✅ | ✗ | n/a | n/a |
| Container isolation | ✗ | ✗ | ✅ | ✅ | ✗ | ✗ | n/a | ✅ |
| OTel export | ✗ (P1) | ✅ | ✅ | ◐ | ✅ | ✅ | ✅ | ✗ |
| Budgets / quotas over time | ✗ (designed, deferred) | ◐ rate limits | ✗ | ✗ | ◐ | ◐ blast radius per call | n/a | n/a |
| One-command install | ✅ `uvx agent-trust-plane` *new* (wheel verified; not on PyPI) | ✅ binary/Helm | ✅ binary | ✅ Docker Desktop | ◐ Docker/pip | ◐ pip | ✅ npx | ✅ pip |
| Property-based tests of security invariants | ✅ *new* | ? | ? | ? | ? | ✗ | n/a | n/a |
| Independent security audit | ✗ | ? | ? | ? | ? | ✗ | ? | ? |
| Production deployments claimed | ✗ (none) | ✅ | ✅ | ✅ | ✅ | ✗ | ✅ | ✅ |

Reading the matrix honestly: ATP's column is unique in the middle block
(delegated authority, execution binding, replay, regression, impact,
mutation) and empty in the operational block (hosting, isolation,
secrets, transports served, approval). That is the positioning: a
decision-and-evidence layer that sits beside a gateway, not a gateway.
