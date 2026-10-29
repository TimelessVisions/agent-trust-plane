# Scope draft — developer-use release

Product name in these documents: **the agent authorization platform**.
Repository, distribution, and CLI stay `agent-trust-plane` / `atp` until
the owner picks a name. Version stays **0.3.2**. This is not a `1.0.0`
proposal and not a certification.

Verdict for a tag or a public release: **no-go**. The draft is a measured
developer-use slice plus an honest limit list. Open P1 items are in
`BLOCKERS.md`.

## In scope for this developer-use slice

A local developer can put `atp mcp wrap` in front of one MCP server and:

1. Delegate a narrow capability set to the session agent.
2. Have an allowed `tools/call` forwarded to that server, and the real
   side effect happen.
3. Have a call the agent is not allowed to make denied in enforce mode
   **before** the upstream tool function runs, with the denial on a
   hash-chained trace.
4. Run `atp policy explain` on that trace.
5. Pin it with `atp regression add` and fail `atp test` when the declared
   policy that produced the denial is removed.

Tested on this branch, Python 3.12.3, Linux, mcp 2.2.0, 2026-10-29:
stdio upstream and Streamable HTTP upstream (localhost), client using the
initialize handshake at revision `2025-11-25`. Evidence:
`TEST_EVIDENCE.md`.

The authorization kernel behind that path is unchanged: delegation
narrowing, single-use execution grants, fail-closed unmapped tools, and
decision-only regression runs. Those already had tests at the baseline
(439 passed, 1 skipped). This draft does not re-prove every kernel
property; it re-ran the suite (445 passed, 1 skipped) after the protocol
field fix.

## Support matrix

Only rows marked measured were executed on this VM on 2026-10-29 against
mcp 2.2.0. “Not supported” means this product must not be described as
providing that surface.

| Surface | `2025-11-25` (initialize handshake) | `2026-07-28` (stateless, `server/discover`, no session) |
|---|---|---|
| Proxy served to the client over **stdio** | **Measured.** `ClientSession.initialize` returned `2025-11-25`. Allowed write forwarded. Unauthorized delete absent from the upstream journal. | **Not a supported revision.** Measured only: `Client` `mode="auto"` and `mode="2026-07-28"` reported `2026-07-28`, and the same delete was still absent from the journal. That is one `tools/call` boundary through the SDK’s dual-era server loop. It is not an implementation of the 2026 lifecycle. |
| Upstream over **stdio** | **Measured.** Trace provenance `protocol 2025-11-25`, transport `stdio`. | **Not measured.** The proxy’s upstream client calls `initialize()` only. |
| Upstream over **Streamable HTTP** (`127.0.0.1`) | **Measured.** Same allow/deny/journal result. Trace provenance contains `http` and `protocol 2025-11-25`. | **Not measured.** |
| Proxy **serving** Streamable HTTP | **Not supported.** `serve()` uses `stdio_server()` only. | **Not supported.** |
| Legacy HTTP+SSE | **Not supported.** | **Not supported.** |
| `tools/list`, `tools/call` | **Measured** on the handshake path (list is covered by older e2e tests; this draft’s new tests call write and delete). | `tools/call` only, and only as the partial stdio measurement above. `tools/list` was not asserted for the modern client. |
| `input_required`, tasks, prompts, resources, notifications, cancellation | **Not supported.** Non-complete tool results are refused in code after the upstream returns. Not exercised with a live `input_required` result. | **Not supported.** MRTR was not implemented. |
| `Mcp-Method` / `Mcp-Name` header routing, list caching, OAuth `iss` / CIMD | **Not this product.** | **Not implemented and not tested.** |
| `@modelcontextprotocol/server-filesystem` | Opt-in test, **not run** (`ATP_E2E_NPX` unset). | Not run. |
| Claude Desktop, Claude Code, Cursor, VS Code, OpenAI Agents SDK, LangGraph, CrewAI, AutoGen | **Not verified.** | **Not verified.** |
| Python 3.12 Linux | **Measured** (this VM). | Partial stdio note above only. |
| Python 3.13, Windows (CI matrix) | **Not measured on this SHA.** The compatibility doc cites an older Actions run; that run was not re-checked here. | Not measured. |
| Python 3.14, macOS | **Not in CI. Not measured.** | Not measured. |

## Out of scope

- Renaming the repository, PyPI distribution, packages, or CLI.
- MCP `2026-07-28` as a supported revision, including stateless HTTP,
  header routing, and multi-round-trip input.
- Serving Streamable HTTP from the proxy.
- Photon iMessage and Telegram alerts (draft PRs #1 and #3). A provider
  accept is not device delivery.
- OPA, OpenFGA, or agentgateway as a new runtime dependency. Comparison:
  `REUSE_DECISIONS.md`.
- A lockfile bump for the pip-audit findings (needs the owner).
- Universal protection against an agent that can open the upstream
  itself.
- Independent audit, production deployment, paid services, branch
  protection changes, tags, or a `1.0.0` version.
- Claiming this worker’s test run is an independent review.

## Acceptance already met on this VM

- Negative test: denied `delete_note` is not in the upstream journal
  (stdio and Streamable HTTP upstream).
- Allowed `write_note` is in the journal and the file contents match.
- Trace integrity valid; explain names the missing capability, or the
  `never-delete` rule when that rule is the reason.
- Editing that rule from `deny` to no rules makes `atp test` exit 1.
- Full pytest on Python 3.12.3: 445 passed, 1 skipped, exit 0,
  2026-10-29T15:32:36Z.

## Acceptance not met

- Supply-chain gate (`BLOCKERS.md` B1).
- Independent re-run (B2).
- CI on this SHA for 3.12, 3.13, and Windows (B5).
- Any wording that the proxy stops a caller who never uses the proxy (B3).
- Any wording that `2026-07-28` is supported (B4).

## Name shortlist

For the owner. Not applied anywhere in code:

The shortlist is in the pull request description so a rename is a
separate decision. Until then, new docs say “the agent authorization
platform”.
