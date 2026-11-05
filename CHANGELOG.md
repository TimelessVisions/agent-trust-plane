# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog; versions follow SemVer while the API is 0.x (breaking
changes may land in minor versions and are called out).

## [Unreleased]

### Added
- A working `REQUIRE_APPROVAL` path. `POST /approvals/{trace_id}` (operator
  key; body `{approver, decision: "approve"|"deny", expires_in: "15m"}`) and
  `atp approve TRACE_ID --as APPROVER_ID [--deny] [--expires 15m]` (local
  home, or `--gateway URL` with `$ATP_OPERATOR_KEY`) record a decision bound
  to the trace's `action_hash` and signed with the active grant key. The
  approver must hold the decision's `approver_role` in the new
  `ATP_APPROVER_ROLES` setting (`human:alice=finance-manager;...`). When the
  agent re-submits the identical envelope, the gateway mints exactly one
  grant; a second retry is `APPROVAL_ALREADY_USED`. New reason codes
  `APPROVAL_ALREADY_USED`, `APPROVAL_DENIED`, `APPROVAL_EXPIRED`,
  `APPROVAL_INVALID`, `APPROVAL_NOT_REQUESTED`, `APPROVAL_ALREADY_DECIDED`,
  `APPROVER_ROLE_MISSING`; new audit events `approval_granted` and
  `approval_denied`. The MCP proxy's REQUIRE_APPROVAL denial names the trace
  and `atp approve <trace>`, and re-sends the same envelope when the agent
  repeats the identical call. See `docs/policies/approvals.md`.
- `atp keygen --rotate` makes a new active grant key for the ATP home
  (`--home`, `$ATP_HOME` or `./.atp`), or for a serve `.env` with
  `--env PATH`. The old private key is deleted, and its public key keeps
  verifying for one grant TTL after the rotation time, which is stored in
  `grant-<kid>.retired`; restart the gateway to load the new key.
- `atp migrate PATH...` brings `atp-mcp.yaml`, `policies.yaml` and
  regression suites to the current file format version in place. The kind
  of each file is detected from its content, not its name. It adds
  `version: 1` above the first key (after any `---` line) and keeps
  comments, line endings and a UTF-8 BOM; it turns `version: "1"` or `1.0`
  into `1`. A file whose comments it could not keep (a flow mapping with
  comments) is refused with exit 2 and left unchanged. A JSON suite stays
  JSON. Through a symlink it updates the file the link points at. It is
  idempotent, prints one line per file, and exits 2 on a file it does not
  recognise or a version it does not support.
  `atp regression migrate` is an alias.
- Declarative policy rule kind `argument_subset_of`: passes when every item
  of a list argument is in `values`, using the same exact-type comparison as
  `argument_allowed_values` (`1`, `"1"` and `true` are distinct). A scalar
  counts as one item and an empty list passes. Denies with
  `ARGUMENT_NOT_ALLOWED`, reporting the allowed values and the offending
  items; a dict, null, float or nested list denies with `ARGUMENT_INVALID`.

### Changed
- **BREAKING:** cumulative spend budgets with reservation semantics. A
  delegation grant's `constraints` take `budget: {amount: Money, period:
  day|week|month}` (UTC calendar periods; a week starts on Monday), and
  `atp-mcp.yaml` `authority` takes the same `budget`, which `atp mcp wrap`
  puts on the session agent's grant. `authorize` reserves the amount
  atomically when it mints a grant (SQLite `BEGIN IMMEDIATE` plus a sum
  check), execution settles it, a failed outcome releases it, and a
  reservation whose grant expires unused is released lazily (next
  reservation, `atp trace list`); once consumed (e.g. released to an
  external executor) it is held until an outcome is reported. Only an
  argument named `amount` is budgeted. Replay of a budget denial reports
  `budget_reevaluated: false` and no outcome change. Every budget on a chain
  applies; the tightest binds. Over budget is DENY with the new reason code
  `PAYMENT_EXCEEDS_BUDGET`, and `atp policy explain` shows `limit`,
  `spent`, `reserved` and `requested`. Breaking: `EffectiveAuthority` (in
  every recorded decision) gains `budgets`, `AuthorityConstraints` gains
  `budget`, the database gains a `budget_reservations` table, and an action
  with an `amount` under a budgeted chain in another currency, or with an
  invalid amount, is now denied. An approval never lifts a budget. See
  `docs/policies/policies.md`, "Budgets".
- **BREAKING:** execution grants are Ed25519 with a key id. The token is
  `atp-grant/2`: `b64url(header).b64url(claims).b64url(sig)` with header
  `{"alg": "EdDSA", "kid": <kid>, "v": "atp-grant/2"}`, the signature over
  the first two segments, and `kid` = the first 16 hex characters of SHA-256
  over the raw public key. `atp-grant/1` (HMAC) tokens are rejected with
  `GRANT_MALFORMED`; an unknown `kid` is `GRANT_SIGNATURE_INVALID`. Claims no
  longer carry `v` (it is in the header); stored 0.3 grant rows still load.
  The `grant_issued` trace event records `kid` instead of `key_fingerprint`.
- **BREAKING:** grant keys are files. The ATP home keeps
  `.atp/keys/grant-<kid>.key` (PKCS8 PEM, mode 0600 where the OS allows) and
  `grant-<kid>.pub`, and `keys.env` holds `ATP_GRANT_SIGNING_KID`; the
  private key is never written to an env file. A 0.3 home's HMAC
  `ATP_GRANT_SIGNING_KEY` is migrated once by `AtpHome.ensure()` (and by any
  offline command that opens the home): an Ed25519 key is generated, then the
  HMAC line is removed, keeping the operator key and comments; `.gitignore`
  gains `keys/`. Traces and evidence bundles are keyless hash chains and still
  verify. A persistent `atp serve` gateway configured only with
  `ATP_GRANT_SIGNING_KEY` refuses to start; `atp keygen --write .env` now
  writes `ATP_OPERATOR_KEY`, `ATP_GRANT_KEYS_DIR` and `ATP_GRANT_SIGNING_KID`
  and puts the key pair in `atp-keys/` next to the file (or `--keys-dir`).
  `GatewaySettings.signing_key_bytes()` is removed; use `grant_keyring()`.
  `cryptography>=50` is a new dependency.
- **BREAKING:** the MCP proxy refuses a config that gives the upstream
  `ATP_GRANT_SIGNING_KID`, `ATP_GRANT_KEYS_DIR`, `ATP_HOME`, a PEM private
  key, a `grant-<kid>.key` path or the grant key directory, in
  `upstream.env`, `headers`, `headers_env` or `args`. The non-loopback
  upstream warning names the grant key too.
- **BREAKING:** `atp-mcp.yaml` (`ProxyConfig`), `policies.yaml`
  (`PolicyFile`) and regression suites (`Suite`) have a top-level
  `version: 1` (`Literal[1]`). Any other value, including `2`, `"1"`,
  `1.0` and `true`, is refused with "unsupported atp-mcp.yaml version 2;
  this atp supports 1" (or `policies.yaml` / `regression suite`). The proxy
  config had no `version` field before, so `version:` in it used to be an
  unknown-key error.
- **BREAKING (deprecation):** a file without `version:` still loads as
  version 1, but emits one `UnversionedFileWarning` (a `DeprecationWarning`
  subclass, exported from `atp_core`) per file per process; `atp`,
  `atp-mcp-proxy` and `python -m atp_gateway` print it as one `warning:`
  line on stderr. Run `atp migrate` to add the field.
  Code that turns `DeprecationWarning` into errors will fail on unversioned
  files. `policy_sets[].version` is unchanged: it is a set's name.
- `atp mcp init` writes `version: 1` as the first key of `atp-mcp.yaml`, and
  `dump_policy_file` writes `version: 1` first.
- `argument_required` treats an argument sent as an explicit `null` as
  missing and denies with `ARGUMENT_MISSING`; it used to pass. This matches
  optional `argument_*` rules, where `null` counts as absent.
  `argument_forbidden` still treats `null` as present and denies.

### Security
- Lockfile pins the lowest releases that clear PYSEC-2026-4320
  (`certifi==2026.10.19`), CVE-2026-114603 (`opentelemetry-api==1.45.1`),
  and PYSEC-2026-4141 / PYSEC-2026-4183 (`pyjwt==2.15.0`). Product version
  stays 0.3.2. Reachability is recorded in
  `docs/release-v1/REUSE_DECISIONS.md`.
- The MCP proxy refuses a config that copies `ATP_OPERATOR_KEY`,
  `ATP_GRANT_SIGNING_KEY`, or the agent token into the upstream. A
  non-loopback HTTP upstream logs a warning. The proxy still cannot
  detect an agent that launches the upstream itself. See
  `docs/release-v1/SECURITY_AND_LIMITS.md`.

### Fixed
- The MCP proxy stamps each envelope with the matched `ToolMapping.tool`.
  It used `mcp.<server_name>` for every call and ignored the mapping, so a
  declared rule whose `applies_to.tool` named the mapping's `tool` never
  matched. `atp mcp init` still writes `tool: mcp.<server_name>`, so its
  configs behave as before; unmapped calls keep `mcp.<server_name>`.
  A mapping onto a tool the gateway executes itself (`payments`) is refused
  when the config loads, in `atp mcp wrap` and `atp mcp proxy` alike.
  `atp mcp wrap` releases every mapping `tool` to the proxy by adding it to
  `ATP_EXTERNAL_TOOL_PREFIXES` (default `mcp.`). A remote gateway needs any
  mapping `tool` outside `mcp.` in its own `ATP_EXTERNAL_TOOL_PREFIXES`.
  The benchmark no longer retargets rules to `mcp.<server_name>`.
- `argument_max_length` denies a non-optional explicit `null` argument with
  `ARGUMENT_INVALID`; it was measured as the 4-character string `"null"` and
  passed under any limit of 4 or more.
- Declarative `argument_*` rules with `optional: true` now treat an argument
  sent as an explicit `null` like an absent one (pass). Previously
  `argument_subset_of` and `argument_allowed_values` denied it. Without
  `optional`, `null` is denied as before.
- `argument_allowed_values` no longer raises `UnicodeDecodeError` when the
  argument is a dict or list whose canonical JSON has a multibyte character
  at byte 200; it denies with `ARGUMENT_NOT_ALLOWED` as intended.
- CI runs pytest with the warnings plugin enabled, so
  `DeprecationWarning` from `atp_*` fails the job. The opt-in third-party
  filesystem server is reported as NOT_MEASURED instead of disappearing
  inside a green test run.
- MCP proxy traces record the upstream `initialize` protocol revision. The
  proxy was reading the camelCase alias attribute, so every trace said
  `protocol unknown`.

### Tests
- A sandbox MCP server journals each tool name before any file change. New
  tests require an allowed write to be received, an unauthorized delete to
  be absent from that journal, the denial to be explainable, and a policy
  edit to fail the pinned regression check. Version is unchanged at 0.3.2.

## [0.3.2] - 2026-09-17

PyPI / distribution-readiness patch release. No product features; the
authorization kernel, policies, CLI commands and wire formats are unchanged
from 0.3.1. Not yet published to PyPI at the time of tagging.

### Packaging
- PyPI-safe README: every documentation link and the hero image are
  absolute GitHub URLs, so the long description renders on pypi.org (which
  does not resolve repository-relative paths).
- Package metadata: descriptive summary, keywords, accurate classifiers
  (Alpha, Python 3.12–3.14, Windows/Linux, Typing :: Typed) and project
  URLs (Homepage, Repository, Issues, Documentation, Changelog, Security).
- Second console entry point `agent-trust-plane` (same CLI as `atp`) so
  `uvx agent-trust-plane …` works after publication (`uvx` runs the
  executable named after the package).
- Build backend pinned (`hatchling==1.32.0` via
  `tool.uv.build-constraint-dependencies`) so a wheel built from the same
  tag anywhere is byte-identical.

### Release engineering
- `.github/workflows/publish.yml`: PyPI Trusted Publishing workflow using
  GitHub OIDC (no PyPI token anywhere). Runs only on a published GitHub
  Release or manual dispatch with a tag; never on push or pull request.
- Gates before upload: strict `v<major>.<minor>.<patch>` tag validation
  (the tag is never interpolated into a shell), pre-release/draft refusal,
  released-commit == checked-out commit, tag == `pyproject` version ==
  wheel version, `twine check --strict`, `scripts/check_dist.py`
  (metadata, contents, secrets, private-dependency and relative-link
  scan), isolated `uvx` smoke test under both executable names, and a
  sha256 re-verification of the artifacts in the publish job.
- `scripts/check_dist.py` also runs in the `package` CI job on every push,
  so the publish gate is exercised before it is ever used for real.
- `docs/release/pypi-publishing.md`: publishing runbook (pending
  Trusted Publisher, `pypi` environment, release procedure, rollback).

### Verification
- Linux dependency-license resolution reviewed (`docs/release/licensing.md`):
  all resolved distributions carry permissive licenses; `uvloop` (Linux-only)
  is MIT.
- Dependency vulnerability audit (pip-audit against the PyPI advisory
  database): no known advisories in the tested resolution. This is
  "no known advisories", not a security guarantee.
- Existing cross-platform CI (ubuntu 3.12/3.13, windows 3.13, package,
  dashboard) remains green.

## [0.3.1] - 2026-09-17

Patch release following the first public GitHub Actions run.

### Fixed
- `atp demo wrap --out <relative path>` resolved the output directory twice:
  the demo runs its own `atp` subprocesses with `cwd=<out>`, so a relative
  `--out` produced paths like `out/out/.atp`. The directory is now resolved
  to an absolute path first. Found by the first CI run on all three OS legs;
  local runs had only used an absolute temporary directory.
- Regression test `test_demo_wrap_accepts_a_relative_out_dir` covers the
  failing shape.

### Verified (GitHub Actions run 35234834560, and again on the docs commit)
- ubuntu-latest, Python 3.12 and 3.13: lint, mypy, full test suite, evals,
  doctor, demos A–D, sample suite, impact, link check
- windows-latest, Python 3.13: same job set
- `package` job: wheel build, isolated `uvx` run, pip-audit, CycloneDX SBOM
- `dashboard` job: typecheck, production build

macOS is not in the CI matrix and is not verified. No IDE MCP client has
been tested. Nothing is published to PyPI. This is not production software
and has not been independently audited.

### Changed
- Compatibility matrix, verification record, roadmap and hostile review
  updated to reflect the remote CI results; stale "CI has not run on a
  remote" statements removed.

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
