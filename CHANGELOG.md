# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog; versions follow SemVer while the API is 0.x (breaking
changes may land in minor versions and are called out).

## [Unreleased]

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
