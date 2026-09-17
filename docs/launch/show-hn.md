# Show HN (draft — not published)

Title: Show HN: Agent Trust Plane – authorization boundary and regression tests for AI agent tool calls

Text:

I built a small open-source tool for the part of agent security that
happens at the tool call. It sits in front of an MCP server, turns every
`tools/call` into a decision against *delegated* authority (a human
delegates limits to an agent; a child can only narrow), decides on the
arguments (amount, path, destination), binds an allow to a single-use grant
over the exact action hash, and records everything on a hash-chained
trace. Then, offline: explain a denial, replay recorded actions under a new
policy to see what flips, mutate a recorded action to look for holes, and
pin a decision as a YAML test that fails CI if it ever changes.

`uv run atp demo wrap` runs the whole loop against a real MCP server in
about 40 seconds from a cold clone; `atp mcp init -- <your server>` then
`atp mcp wrap` does it for yours. There is a shadow mode so you can observe
before enforcing.

What it is not: a gateway. No hosting, isolation, secrets, served HTTP
transport. The boundary only holds if the agent cannot reach the server
without the proxy, which is a deployment property, and the docs say so. The
policy language is deliberately tiny (OPA/Cedar adapters are the plan). No
users yet, not audited; the threat model separates guarantees from
assumptions and gaps, and there is a hostile self-review in the repo.

I would like to know whether the generated capability proposals make sense
for servers other than the two I tested against, and what people need
before trusting shadow → enforce.
