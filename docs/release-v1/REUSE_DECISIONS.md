# Reuse decisions — the agent authorization platform

Research date: 2026-10-29. Primary sources were read before the test patch.
Nothing here is an exclusivity claim, a security review, or a certification.
Popular projects were not treated as reviewed just because they are maintained.

## Decision 1 — keep the in-repo proxy; fix the recorded protocol field

### Requirement and gap

Operators need the trace to name the MCP revision the proxy actually
negotiated with the upstream, and tests need to show that a denied delete
was not delivered.

- Before this branch, `connect_upstream` stored
  `getattr(init, "protocolVersion", None)`. On mcp 2.2.0 the attribute is
  `protocol_version`, so every trace’s task description was
  `protocol unknown`. Failing tests:
  `adapters/mcp/tests/test_deny_before_upstream.py`
  (`test_allowed_write_is_forwarded_and_delete_is_not_received`, both
  transports, and `test_removing_the_deny_rule_fails_the_regression_check`).
  After the fix the same tests require `protocol 2025-11-25`.
- Existing allow/deny tests (`adapters/mcp/tests/test_proxy_e2e.py`,
  `packages/cli/tests/test_wrap_e2e.py`) treat “the note file still exists”
  as proof the upstream was not called. That is a side effect of this
  notes server’s `unlink`, not a receipt log. The new sandbox journal is
  written inside the tool, before the file change.

### References inspected

| Project | What was read | Version / date | License | Maintenance | Security note from the source, not a review |
|---|---|---|---|---|---|
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk release v2.2.0 and the v2 protocol-versions / what’s-new docs; PyPI file hashed in `uv.lock`; installed package `mcp_types/version.py` | Pinned **2.2.0** (the v2.2.0 GitHub release names commit `9972c21`, published 2026-09-07). Latest GitHub release inspected via the API: **v2.3.0**, published 2026-10-02. Repo `pushed_at` 2026-10-27. | MIT | Active. v2.3.0 exists after the pin; it was not adopted. | v2.2.0 release notes: tasks extension (SEP-2663), DPoP (SEP-1932), and the `jwt-bearer` grant are not implemented. HTTP redirects are origin-bound. This repo was not upgraded and those gaps were not re-tested. |
| MCP spec revision note | https://blog.modelcontextprotocol.io/posts/2026-07-28/ | Post dated 2026-07-28, authors David Soria Parra and Den Delimarsky | Spec post, not a library | The post says Tier-1 SDKs, including Python, speak `2026-07-28` as of that day. | The revision removes `initialize` / sessions, adds `server/discover`, `Mcp-Method` / `Mcp-Name` headers, MRTR (`input_required`), cacheable lists, and a different authorization posture (RFC 9207 `iss`, CIMD, DCR deprecated). |
| agentgateway | https://github.com/agentgateway/agentgateway and https://agentgateway.dev/docs/standalone/latest/configuration/security/mcp-authz/ | Release **v1.7.0**, published 2026-10-27 (GitHub API). Repo `pushed_at` 2026-10-29. License from the GitHub API: Apache-2.0. | Apache-2.0 | Release the same week as this research. | Their MCP authorization page says request-time rules can use `mcp.tool.name`, `mcp.tool.target`, and `mcp.methodName`. The same page states `mcp.tool.arguments` is **not** set when `mcpAuthorization` rules run. Argument checks are described there as a route-level `authorization` policy. The v1.7.0 notes say standalone deployments encrypt MCP sessions unless `config.session.key` is `disabled`. |
| Open Policy Agent | https://github.com/open-policy-agent/opa releases | **v1.21.4** (`05c8451`, published 2026-10-23). Repo `pushed_at` 2026-10-29. | Apache-2.0 | The 1.21.4 note is a Go toolchain rebuild (Go 1.27.3), not an MCP feature. | No MCP transport. This repo’s `docs/policies/why-not-just-opa.md` already says an OPA adapter is not built. |
| OpenFGA | https://github.com/openfga/openfga releases and https://openfga.dev/docs/modeling/agents/mcp-authorization | **v1.22.1** (`44054f5`, published 2026-10-28). Repo `pushed_at` 2026-10-29. License confirmed from the module metadata as Apache-2.0. | Apache-2.0 | v1.22.1 is a patch the day before this research. v1.22.0 (2026-10-06) records a grpc bump for GO-2026-6443. | The MCP guide models who can call a tool (public, role, group, temporal grant, resource relations). It is not an MCP proxy and the page that was read does not show argument-level comparison inside a tool call. |

### Options

| Option | Why it lost or won |
|---|---|
| Adopt agentgateway as the proxy | It is a maintained MCP gateway and it already filters tools. It does not, by itself, give this repo’s hash-chained trace, single-use execution grant, or `atp test` regression file. Replacing the proxy would be a new Rust runtime and a new policy language (CEL). The measured bug was a wrong attribute name. |
| Adopt OPA or OpenFGA as the decision engine | Both are the right shape for *some* authorization questions. Neither one is the MCP session, the grant, or the regression runner. `docs/policies/why-not-just-opa.md` already records that an adapter was rejected for this codebase. Adding either dependency does not fix the journal gap or the protocol field. |
| Upgrade mcp from 2.2.0 to 2.3.0 | The installed 2.2.0 already contains the dual-era server used by the proxy. 2.3.0 was not diffed test-by-test. An upgrade is a behavior change, not the smallest fix, and this task forbids a version bump of the product. The dependency pin stays. |
| **Retain the proxy and policy engine. Narrow custom fix plus tests.** | The kernel already denies before `session.call_tool`. The missing pieces were an upstream receipt assertion, a regression test that edits a declared rule, and reading `protocol_version`. |

### Why this beat a rebuild

The allow path, the capability denial, `atp policy explain`, and
`atp regression add` / `atp test` already existed and passed at the
baseline (439 passed, 1 skipped). Rebuilding that loop inside
agentgateway, Rego, or OpenFGA would replace tested code to gain a
gateway or a policy language this release does not need. The validation
is the new tests plus the previous suite: 445 passed, 1 skipped, on
2026-10-29T15:32:36Z.

We do **not** claim to be the only project that can deny an MCP tool call
using arguments. agentgateway documents argument-aware checks on its
route authorization policy. OPA and OpenFGA can express authorization
data this engine does not try to match. The property this repository
pins is a recorded decision that `atp test` recomputes, without calling
the tool.

## Decision 2 — do not implement MCP `2026-07-28` in this change

### Requirement and gap

The product must not be described as speaking the 2026-07-28 revision
unless that lifecycle is implemented. The proxy serves stdio with
`Server.run` and `create_initialization_options()`, and its upstream
client calls `ClientSession.initialize()` (`proxy.py`, `connect_upstream`
and `serve`). That is the handshake era. `2026-07-28` drops the handshake.

SDK constants in the installed 2.2.0 (`mcp_types/version.py`):

- `HANDSHAKE_PROTOCOL_VERSIONS` ends at `2025-11-25` (`LATEST_HANDSHAKE_VERSION`).
- `MODERN_PROTOCOL_VERSIONS` is `("2026-07-28",)`.
- `LATEST_PROTOCOL_VERSION` is `2026-07-28` for the SDK as a whole, not for this proxy’s supported surface.

A measurement, not a support claim: `Client` `mode="auto"` and
`mode="2026-07-28"` against the stdio proxy both reported protocol
`2026-07-28`, the allowed write was journaled, and the unauthorized
delete was not (`test_modern_client_cannot_deliver_a_denied_delete`).
The trace for that denial still records the **upstream** handshake
revision `2025-11-25`, because the proxy’s upstream client still calls
`initialize()`. MRTR, `Mcp-Method` header routing, stateless HTTP
serving, tasks, and cache hints were not implemented and not tested.

### Options

| Option | Result |
|---|---|
| Pretend the SDK constant `LATEST_PROTOCOL_VERSION` means this product supports 2026-07-28 | Rejected. That would be a false claim. |
| Rewrite the proxy onto the stateless client/server API | Deferred. It is a lifecycle change (no session, MRTR instead of server-initiated requests). Out of scope for the first proof. |
| **Retain handshake behavior, test the accidental stdio tools/call path, document it as not supported.** | Chosen. The security invariant (denied delete not in the journal) is locked. The support matrix says the revision is not supported. |

## Decision 3 — do not merge the Photon or Telegram alert branches

### Requirement and gap

The program asks for an optional device notification only after the deny
path is real, and says a provider accept is not delivery. PR #1 and PR #3
are drafts. PR #3 is stacked on PR #1. Issue #4 asks for an npm audit of
the Spectrum SDK before production. This branch does not include those
diffs (Photon PR changes `proxy.py`, the CLI, and `uv.lock` relative to
`main`).

### Options

| Option | Result |
|---|---|
| Merge or rebase onto the alert branches | Rejected for this proof. They are experimental notification channels, not the authorization decision. |
| **Leave them open and independent.** | Chosen. An alert channel can be considered later, with its own tests, and must not be described as confirmed device delivery unless a device receipt is shown for that run. |

## Decision 4 — bump three locked transitive versions, nothing else

### Requirement and gap

`pip-audit` 2.10.1 on the locked runtime set (`uv export --no-hashes
--no-emit-project --no-dev`, then `--disable-pip --no-deps --strict`)
exited 1 at 2026-10-29T15:44:19Z on `18d910e`:

| Package | Locked before | Advisory | Fix version named by the audit |
|---|---|---|---|
| certifi | 2026.7.22 | PYSEC-2026-4320 | 2026.10.18 and 2026.10.19 |
| opentelemetry-api | 1.44.0 | CVE-2026-114603 | 1.45.1 |
| pyjwt | 2.14.0 | PYSEC-2026-4141, PYSEC-2026-4183 | 2.15.0 |

None of the three is a direct dependency of this repository. `mcp==2.2.0`
requires `opentelemetry-api>=1.28.0` and `pyjwt[crypto]>=2.10.1`.
`certifi` is pulled in by the HTTP stacks. Product version stays 0.3.2.

### Reachable here, or not

Checked against installed mcp 2.2.0 and this repository’s source on
2026-10-29. This is call-graph evidence, not an exploit and not a
statement that the advisory is harmless in general.

**certifi PYSEC-2026-4320.** The advisory describes the emSign ECC Root
CA G3 in the bundled trust store, with compromised intermediate keys, and
says an on-path attacker who holds one of those keys can impersonate TLS
hosts. Certifi 2026.10.18 is still listed in the affected version set that
was read with the advisory; 2026.10.19 is the release the advisory text
tells clients to install (it restores the unaffected emSign roots). This
repository does not import `certifi`. `httpx` / `httpx2` do, and the proxy
builds an `httpx2` client for a Streamable HTTP upstream
(`adapters/mcp/src/atp_adapter_mcp/proxy.py`). The stdio notes path does
not open TLS. An HTTPS upstream or an HTTPS gateway URL uses that CA
bundle. So the bad root is on the TLS path this program can take, and it
is not on the stdio demo path. The pin is `certifi==2026.10.19`, the
lowest version that covers both fix lines the audit printed. PyPI’s
latest on this date was 2026.10.23; that was not taken.

**opentelemetry-api CVE-2026-114603.** `TraceState.from_header` can spend
quadratic time on a `tracestate` value that is a long run of spaces or
tabs. mcp’s `Server` installs `OpenTelemetryMiddleware` by default
(`mcp/server/lowlevel/server.py`). That middleware calls
`extract_trace_context(ctx.meta)` on the inbound message
(`mcp/server/_otel.py`), and `extract_trace_context` calls
`opentelemetry.propagate.extract` (`mcp/shared/_otel.py`). `ctx.meta` is
taken from the request `_meta`. The proxy uses that `Server`. A client of
the proxy can therefore put a `tracestate` value on a message the
middleware extracts, on the stdio server path, before the tool handler
runs. No exporter is required for the parse. **Reachable on the proxy’s
request path.** The pin is `opentelemetry-api==1.45.1`, which is also the
newest release published on this date. This change does not add a test
that sends a hostile `tracestate`.

**PyJWT PYSEC-2026-4141.** Deeply nested JSON in a token payload can raise
`RecursionError` from `jwt.decode` / `PyJWKClient.get_signing_key_from_jwt`
when signature verification is off. The only `import jwt` in installed
mcp 2.2.0 is `mcp/client/auth/extensions/client_credentials.py`, and the
call there is `jwt.encode` for a private-key JWT client-credentials
grant. This repository does not import `jwt`, `PyJWKClient`, or that
extension. **Not reachable on the gateway, CLI, or proxy paths that this
tree executes.**

**PyJWT PYSEC-2026-4183.** From 2.1.0 until 2.15.0, `OKPAlgorithm.from_jwk`
does not check that an OKP private JWK’s `x` matches the public key
derived from `d` (OSV, CVSS 3.1 8.2, fixed in 2.15.0). The described
attack also needs an integration that accepts private-key parameters from
a proof header. This tree does not call `from_jwk`. **Not reachable on
the paths this tree executes.** The same pin, `pyjwt==2.15.0`, is the
lowest release the audit names for both PyJWT ids. PyPI’s latest on this
date was 2.15.1; that was not taken.

### Options

| Option | Result |
|---|---|
| Leave the lockfile and accept a red `package` job | Rejected for this branch. The director asked for the minimum bump in a draft PR. |
| Upgrade mcp, or float every dependency | Rejected. `uv lock` changed three versions and left the package count at 71. |
| **Exact constraints at the minimum fix versions, regenerate `uv.lock`.** | Chosen. `[tool.uv] constraint-dependencies` pins `certifi==2026.10.19`, `opentelemetry-api==1.45.1`, `pyjwt==2.15.0`. |

Merging the lockfile is an owner decision. This PR does not merge.
