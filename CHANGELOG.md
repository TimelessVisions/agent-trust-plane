# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog; versions follow SemVer while the API is 0.x (breaking
changes may land in minor versions and are called out).

## [Unreleased]

## [0.3.0] - 2026-09-17

Category: action control and security regression infrastructure for AI tool
use ([ADR-0003](docs/adr/0003-category-definition.md)).

### Added
- `atp mcp init -- <command>` / `--url`: discover an MCP server's tools and
  write a reviewed-by-you proxy config plus a declared policy set.
- `atp mcp wrap`: serve a protected MCP server with the gateway running
  in-process from a local-first `.atp/` home (keys generated once, SQLite
  evidence store). `--mode shadow` observes without blocking.
- Shadow enforcement mode: `Decision.enforcement`, `shadow_would_deny` /
  `shadow_execution_*` events, `POST /traces/{id}/shadow-outcome`,
  `WOULD_DENY` labels; the mode is a gateway setting a caller cannot request.
- Prefix resource scopes (`path:/dir/*`) and path normalisation in tool
  mappings (`..`, separators, optional case folding, `base_dir`).
- Declared policy sets (`policies.yaml`, eight rule kinds) loaded beside the
  built-ins; the kernel policies always apply.
- `atp policy explain` (why + what would need to change), `diff`, `impact`
  (`--fail-on-widen`), `coverage`; `atp mutate` (offline request mutation,
  authorize only); `atp regression add` from the local store; `atp trace
  list/show`; `atp evidence export/verify` (hash-checked bundles).
- Streamable HTTP upstreams for the proxy (`upstream.url`, `headers_env`).
- `IdentityProvider` protocol; `BearerCredentialProvider`; `InProcessAgentClient`.
- Property-based tests (Hypothesis): scope algebra soundness, delegation
  monotonicity, decision determinism, stateful grant lifecycle; exhaustive
  grant state-machine check against a written spec (`docs/formal/`).
- Single distribution `agent-trust-plane` (one wheel, `atp` entrypoint);
  `uvx --from <wheel|git url> atp` verified.
- One SQLite transaction per kernel operation (events + grant state atomic).
- Bounded reads (1 MiB) for every untrusted YAML/JSON input.
- CI: SHA-pinned actions, least privilege, Windows leg, wheel + uvx job,
  pip-audit, CycloneDX SBOM (`scripts/sbom.py`), link check.
- `atp demo wrap`; recorded transcript and rendered SVG (`scripts/record_demo.py`).
- Docs: threat model rewrite, red-team attack log, pre-mortem, first
  principles, research (competitive code review, user pain, rejected ideas,
  A2A), compatibility matrix, boundary/idempotency/trace-integrity/
  identity/privacy/safe-defaults, why-ATP, why-not-OPA, DEVELOPMENT, ROADMAP.

### Changed
- Resource grammar widened (`/` and most printable characters allowed in
  ids); concrete resources may not contain `*`.
- `ToolMapping.resource_arguments` removed (derived from the template);
  resource arguments are no longer stripped from forwarded/hashed arguments;
  resource templates may not contain `*` (`note:*` -> `note:_list`).
- `atp mcp-init` replaced by `atp mcp init`; `atp mcp-proxy` is a hidden
  alias of `atp mcp proxy`; `atp record` kept for remote gateways.
- `GrantStore.revoke` no longer overwrites a consumed grant (state-machine
  finding F18).
- In-process ASGI client uses one long-lived event loop (was one per request).
- Docs moved into `docs/{architecture,security,integrations,regression,policies,research,release,launch,commercial,red-team,formal,archive}/`.

### Removed
- `atp_adapter_mcp.McpInterceptor` (v0.1 in-process shim) and `scripts/demo.sh`.

## [0.2.0] - 2026-09-17

### Added
- `atp` CLI: `doctor`, `demo {injection,regression,mcp}`, `test`, `record`,
  `serve`, `keygen`, `mcp-proxy`, `mcp-init`.
- MCP stdio proxy (`atp mcp-proxy`) fronting one upstream MCP server;
  `tools/call` is authorized, released under a single-use grant, forwarded,
  and its outcome reported. Verified against the in-repo notes server and the
  reference `@modelcontextprotocol/server-filesystem`.
- External-tool execution path in the gateway: `execution_released` event,
  `POST /executions/{grant}/outcome` bound to the grant audience, once.
- YAML security regression suites with JSON and JUnit output; deterministic
  trace-to-case recorder; sample suite; GitHub Actions example.
- Dashboard before/after centrepiece (policy diff, authority, side-effect
  evidence, replay limits).
- Benchmark harness and measured results (`docs/benchmarks.md`).
- `notes-mcp-server` example package; `atp_gateway.local.LocalGateway`.
- Competitive landscape research and product-wedge ADR-0002.
- CONTRIBUTING, SECURITY, issue/PR templates, release process.

### Changed
- README rewritten around the proxy + regression-test journey.
- `/health` no longer lists the signing key fingerprint; tools list now shows
  external prefixes (`mcp.*`).

### Security
- Proxy refuses oversized tool arguments instead of truncating (the grant
  binds the exact argument hash).

## [0.1.0] - 2026-09-16

### Added
- Core control plane: `ActionEnvelope`, delegation chains with intersection
  semantics, versioned policy engine, HMAC single-use execution grants,
  hash-chained trace store, replay, adversarial eval suite, finance-agent
  demo, Next.js dashboard.
- Authenticated agent identity (bearer credentials), operator key, trace
  ownership, operator-only reads, no insecure defaults, concurrency and
  impersonation regression tests, security self-review.
