# LinkedIn (draft — not published)

Shipped v0.3.0 of Agent Trust Plane, an open-source tool for the point
where an AI agent's mistake becomes real: the tool call.

What it does: sits in front of an MCP server, decides each call against
authority a human delegated (limits, paths, capabilities — a child agent
can only narrow), binds an allow to a single-use grant over the exact
action, records everything, and lets you replay, explain and pin denials
as CI tests so a fix cannot silently regress. One command wraps a server;
a shadow mode lets teams observe before enforcing.

What it is not: a gateway, a product, or audited. The docs separate what is
guaranteed from what is assumed (the agent must not be able to reach the
tool without the proxy). Measured, not claimed: 37 s from a cold clone to
the first allow/deny on a real server; ~11 ms added per call with durable
evidence.

Looking for engineers running agents with consequential tools who want to
try it on their own MCP server and tell me where it breaks.
