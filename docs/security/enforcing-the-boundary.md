# Enforcing the boundary

ATP decides and binds. It does not, by itself, stop an agent that can reach
a tool without going through it. Whether the boundary holds is a
deployment property; this page says what that property is and how to get
it.

## Two topologies

```
INSECURE                                   SECURE
--------                                   ------
agent ──▶ tool                             agent ──▶ ATP ──▶ tool
agent ──▶ ATP ──▶ tool                          ▲             ▲
                                                │             └─ reachable only from ATP;
"the agent has a path around ATP"              │                credentials held only by ATP
                                                └─ the only path
```

In the insecure topology every guarantee in the threat model is void:
the decision happens, the evidence is recorded, and the side effect
happens anyway through the other path. The repository demonstrates this
on purpose: `test_direct_upstream_access_is_not_protected` and
`test_in_process_tool_call_is_not_protected`.

## What makes the secure topology true

For an MCP server behind `atp mcp wrap` / `atp mcp proxy`:

| Mechanism | How | Strength |
|---|---|---|
| **Proxy-owned process** | The proxy launches the stdio upstream as its child; no other listener exists; the agent host only has the proxy's stdio | Strong on a single machine if the agent cannot spawn its own copy of the server (see credentials) |
| **Gateway/proxy-owned credentials** | The upstream needs a secret (API token, DB password). Only the proxy's config (`upstream.env`, `upstream.headers_env`) has it; the agent host does not | Strong: without the secret a second copy of the server is useless |
| **Network reachability** | For HTTP upstreams: the server accepts connections only from the proxy's address (firewall, security group, mTLS, private network) | Strong |
| **Service identity** | The upstream authenticates its caller (mTLS/SPIFFE, signed requests) and the proxy is the only principal it accepts | Strong; not provided by ATP, provided by the platform |
| **Sidecar / container** | Agent and proxy in one pod/compose network; the upstream on a network only the proxy joins | Strong with correct network policy |
| **Localhost isolation** | Proxy and upstream on one host, agent on another | Medium: anything on the host can connect |
| **Trust in the agent** | "The agent will not bypass it" | None; this is what prompt injection defeats |

For the built-in payments tool (the demo), there is no boundary: it runs
in the gateway process and a test shows in-process code can call it. It
exists to make evidence inspectable, not to be deployed.

## What ATP contributes to the boundary

- The proxy holds the agent credential and the upstream session; the
  agent never receives the upstream's secrets when they come from the
  proxy config (Phase 23 credential isolation is a *configuration*
  pattern today, not a vault).
- Unmapped tools fail closed, so a new tool on the upstream is not a new
  hole.
- `tools/list` hides what is not mapped, which removes the temptation, not
  the ability.

## What ATP does not contribute

- It cannot detect a bypass. Nothing on the trace says "the agent also
  called the server directly".
- It cannot isolate the upstream (no containers, no namespaces).
- It cannot rotate upstream secrets.

## Checklist before believing a decision

1. Can the agent host launch the upstream itself? If yes, boundary = none.
2. Does the upstream need a secret the agent host does not have? If yes,
   boundary = credentials.
3. Is the upstream network-reachable from the agent host? If yes, boundary
   depends on the upstream authenticating the proxy.
4. Is the proxy's own stdio the only client? (`atp mcp wrap` serves stdio
   to whoever launched it; do not put it behind a shared socket.)

Deployment requirements that follow from this are in
[deployment.md](deployment.md).
