# Name-only reference layer (not a product)

**Type:** Synthetic comparison baseline, not a third-party security gateway.

An MCP client calls a normal AgentDojo suite server. Before each tool call, the name-only
reference checks only whether the function name appears in the same pre-injection
annotation's `capabilities` set. If the name is granted, arguments are passed unchanged;
if it is not granted, the call is blocked locally without reaching the server.

It **does not** enforce `resource_scope`, amount limits, allowed values, list subsets,
required/forbidden arguments, or human approvals. It also does not filter `tools/list`
(the model-free replay uses only the function-call session API). Every dropped
resource scope and rule is recorded with a reference to this document.

This reference is useful for quantifying how much better an argument-aware
authorization system performs than tool-name allowlisting. Results must label
it **name-only reference** rather than attribute its behavior to a commercial gateway.

Run the `name-only` layer without a third-party binary or container runtime:
`cd bench && uv run python -m atp_bench run --layer name-only --suite banking --out /tmp/name-only --injections-per-task 0`.

No preregistered attack sweeps should run before the owner's A1 annotation gate.
