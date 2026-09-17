# r/programming (draft — not published)

Title: Agent Trust Plane: single-use execution grants, delegated authority and regression tests for AI agent tool calls (with a hostile self-review)

Body:

Technical write-up rather than a pitch. The core is small: an action
envelope hashed canonically; delegation chains rooted at a human where each
link can only narrow (checked with property-based tests); a deterministic
policy engine that records every constraint it compared; an ALLOW mints an
HMAC grant bound to the action hash and the agent, consumed atomically once
(the state machine is written down and exhaustively enumerated); every step
on a per-trace hash chain. An MCP proxy is the delivery vehicle.

The parts I think are actually new relative to the gateways I inspected
(citations in the repo): deciding on argument values against *delegated*
limits, decision→execution binding, replaying recorded decisions under a
new policy to see what flips, and request-side mutation of a recorded call
run through authorization only.

The repo includes a "why this is just another toy MCP proxy" review with
the responses, a threat model that separates guarantees from assumptions,
and a compatibility matrix that mostly says NOT VERIFIED. No users; MIT.
