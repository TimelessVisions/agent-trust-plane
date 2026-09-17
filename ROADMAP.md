# Roadmap

No dates. Items move when there is a user asking for them or a test that
needs them. Rejected ideas and why: [docs/research/rejected-ideas.md](docs/research/rejected-ideas.md).

## NOW (v0.3.0 — done in this tree)

- `atp mcp init` / `atp mcp wrap`: one command from an MCP server to a protected one; local-first `.atp/`
- Shadow mode; `WOULD_DENY` on every surface
- Path/prefix scopes with normalisation; declared policy sets
- `atp policy explain / diff / impact / coverage`; `atp mutate`; `atp regression add`; `atp evidence export / verify`
- Streamable HTTP upstream; property-based and exhaustive kernel tests; single installable distribution

## NEXT

- **Publish**: GitHub repository, tagged release, PyPI `agent-trust-plane` (needs maintainer approval; nothing is public yet)
- **Streamable HTTP served by the proxy** with bearer/OAuth client auth (today: stdio only on the served side)
- **Idempotency key injection** as a per-mapping option (`docs/security/idempotency.md`)
- **Identity providers from settings**: SPIFFE/mTLS and OIDC client-credential providers behind the existing `IdentityProvider` protocol
- **Trace export hook**: a `TraceStore` wrapper that streams events to a sink (WORM bucket, log service); signed trace heads for the `atp serve` deployment
- **OpenTelemetry export** of decisions as `execute_tool` spans once the GenAI conventions leave *Development*
- **Chaos tests**: proxy killed mid-call, partition to a remote gateway, second SQLite writer
- Linux/macOS verification of the wrap flow in CI (the workflow targets ubuntu; it has not run on a remote yet)

## LATER

- Policy-engine adapters (OPA/Rego, Cedar) behind the `Policy` boundary; AuthZEN façade
- Interceptor/ext-authz modes for Docker MCP Gateway and agentgateway
- Human approval protocol (bound to action hash, approver identity, expiry)
- Budgets and quotas with reservation semantics (`rejected-ideas.md` has the design constraint)
- Postgres stores; multi-instance gateway
- TypeScript SDK; async Python client
- Dashboard: policy-impact view (only if the CLI output proves insufficient)
- Suite/policy-file schema v2 with `atp regression migrate`

## RESEARCH

- A2A bounded delegation ([docs/research/agent-to-agent-future.md](docs/research/agent-to-agent-future.md))
- Verifying tool side-effect claims (annotations are untrusted; MCP has no way to prove them)
- Symlink-safe path scoping using the upstream's own `roots`
- Policy mutation (mutating the declared set, not the request)
