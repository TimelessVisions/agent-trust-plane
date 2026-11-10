# Docker MCP Gateway — tool-name allowlist competitor

**Status:** Experimental D4 adapter; `ENV_BLOCKED` if Docker Engine or the Docker MCP
Gateway plugin is unavailable. No product comparison rates are claimed while blocked.

## References and interpretation

- [Docker's official gateway README](https://github.com/docker/mcp-gateway/blob/main/README.md)
- [Gateway run flags, `--servers` / `--tools`](https://github.com/docker/mcp-gateway/blob/main/docs/mcp-gateway.md)
- [Remote MCP server catalog definition](https://github.com/docker/mcp-gateway/blob/main/docs/server-entry-spec.md)
- [Catalog schema](https://github.com/docker/mcp-gateway/blob/main/docs/catalog.md)

**No-code configuration:** one tool allowlist entry per capability in the same
pre-injection annotation. Docker MCP Gateway's documented `--tools` controls
tool names; its documented gateway configuration does not provide a general
equivalent of ATP's resource-scope, numeric-limit, allowed-value, or list-subset rules.
These constraints are recorded in `RenderedPolicy.dropped` via `dropped_constraints()`.

## Runtime adapter

1. Run `docker info`; a missing or inaccessible daemon is `ENV_BLOCKED` with stderr.
2. Check `docker mcp gateway run --help`. A missing plugin is `ENV_BLOCKED`,
   not a claim about Docker MCP Gateway's authorization quality.
3. Start the synthetic AgentDojo suite server on local Streamable HTTP.
4. Write an isolated remote-server YAML catalog under an ephemeral
   `HOME/.docker/mcp/catalogs`, never modifying the owner's Docker catalog or profiles.
5. Start `docker mcp gateway run` with only the annotated tool-name allowlist.
6. Classify tool results as forwarded. Unknown error responses remain `INCONCLUSIVE`
   until a pinned Docker MCP Gateway denial shape is verified; never infer DENIED from
   an unknown-tool or transport error.

**Important limitations:** Docker Gateway may rename exposed tools or require a
different catalog transport spelling than this candidate. Its plugin is separate
from Docker Engine and may not be present on standard CI runners. Such behavior
must be tested, not scored from assumptions. This adapter does not claim an audited
Docker-versus-ATP comparison until a verified gateway run and its raw journal exist.

The independent **name-only reference** exists separately and must never be
presented as the actual Docker MCP Gateway.

## Test contract

- `test_docker_absent_is_env_blocked`: mocked Docker failure reports its stderr;
  no request is scored as an authorization decision.
- Name-only tests assert that a granted tool with out-of-scope arguments reaches the
  synthetic server, and an ungranted tool never reaches it.
- A real Docker MCP Gateway run is `NOT_MEASURED` until CLI plugin availability,
  version, allowlisted tool discovery, JSON-RPC denial classification and journal
  behavior are established on the pinned platform.

Do not edit annotation YAMLs or run the owner-gated D5 competitive sweep.
