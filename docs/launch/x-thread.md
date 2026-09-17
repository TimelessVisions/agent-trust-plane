# X thread (draft — not published)

1/ Prompt injection is not the bug. The tool call it produces is. I built
a small OSS boundary for that: Agent Trust Plane v0.3.0.

2/ `atp mcp init -- <your MCP server>` then `atp mcp wrap`. Every
tools/call is decided against delegated authority — amounts, paths,
destinations, not just tool names — and denied calls never reach the
server.

3/ An ALLOW mints a single-use grant over the exact action hash. Change
the arguments after authorization and it is blocked. The grant state
machine is written down and exhaustively checked.

4/ Everything lands on a hash-chained trace in `.atp/`. `atp policy
explain` says which constraint failed and what would need to change.
Derived from the record, not generated.

5/ `atp regression add TRACE` → `atp test`. CI fails if the decision ever
flips. `atp policy impact --from v1 --to v2` shows which recorded actions
change before you ship a policy.

6/ Shadow mode records WOULD_DENY and forwards, so you can observe first.
The mode is set by the gateway; a caller cannot ask for it.

7/ What it is not: a gateway. No hosting, isolation, secrets, served HTTP.
The boundary holds only if the agent cannot reach the server directly —
a deployment property, documented, with the bypass as a test.

8/ No users, not audited, MIT. Cold clone to first allow/deny: 37 s.
Hostile self-review and threat model in the repo. Try it on your server
and tell me where it breaks.
