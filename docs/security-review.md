# Security review (self-conducted, 2026-09-16)

Scope: the gateway, identity, policy, audit, adapters and dashboard as of
commit `e18d86b`. Method: read the code against the checklist below, write an
attack for anything suspicious, keep the attack as a regression test. This is
a self-review by the author, not an independent audit; treat it accordingly.

Severity scale: **High** = money or authority can be obtained without the
intended check; **Medium** = integrity or confidentiality of the audit/
configuration is weakened; **Low** = hardening.

## Findings fixed in this pass

| # | Area | Finding | Severity | Evidence (before) | Fix | Regression test |
|---|---|---|---|---|---|---|
| F1 | Authentication | `envelope.agent` was asserted, not authenticated. Anyone who knew a grant id and an agent id could act as that agent. | High | Threat model v1 listed it as the top gap. | Per-agent bearer credentials (`atpa_<id>.<secret>`, SHA-256 stored, constant-time compare). Authenticated identity must equal `envelope.agent`, the chain's leaf grantee, and the grant's audience. | `test_identity_security.py::TestImpersonation`, EVAL-005(c), EVAL-008 |
| F2 | Authorization | Any caller could issue delegations in a human's name or on another agent's behalf. | High | `/delegations` had no auth. | Human grantor ⇒ operator key; agent grantor ⇒ that agent's credential. | `TestForgery::test_forging_human_authority_via_delegation`, `test_delegating_on_behalf_of_another_agent`, EVAL-003(c) |
| F3 | Authorization | Agents could select a weaker policy set on `/authorize`. | High | `?policy_set_version=payments-v1` from an agent was honoured (first MVP). | Operator key required for override. | `TestPolicySelection` |
| F4 | Audit | Free-text `actor` on provenance events; agents could write events as anyone. | Medium | `POST /traces/{id}/events` accepted `actor`. | Field removed; actor is the authenticated agent; `credential_id` recorded. | `TestForgery::test_forging_audit_actor` |
| F5 | Audit | Any authenticated agent could append events (or trigger `identity_rejected`) onto another agent's trace; trace ids were listable. | Medium | Found in this review. | Trace ownership: first agent to write owns the trace; others get `TRACE_OWNED_BY_OTHER_AGENT`. | `test_agent_cannot_append_to_another_agents_trace` |
| F6 | Revocation | Credential revocation between HTTP-layer authentication and the locked execute path was not re-checked. | Medium | Window between dependency and lock. | Credential status re-checked inside the lock on authorize, execute, and provenance. Delegation revoke/issue moved under the same lock. | `test_revoked_credential_is_rechecked_under_the_lock`, `test_execute_after_delegation_revoked_by_grantor` |
| F7 | Configuration | Ephemeral keys were generated silently for persistent gateways; a public deployment could run with keys nobody knew. | Medium | `signing_key_bytes()` fell back to random. | Persistent gateway refuses to start without ≥32-char keys; `python -m atp_gateway keygen`. Only `:memory:` generates keys. | `TestSecureDefaults` |
| F8 | Exposure | Traces, ledger, delegations, replay and eval results were unauthenticated reads. | Medium | Fine on localhost; exposes vendor accounts and decisions when bound publicly. | Operator key required on all reads except `/health` and `/policy-sets`. Dashboard gates on the key. | `test_reads_are_operator_only` |
| F9 | Exposure | `/health` returned a signing-key fingerprint. | Low | 16 hex chars of SHA-256(key). | Removed. | `test_reads_are_operator_only` |
| F10 | Input | `Money` rounded `1000.004` to `1000.00`. | Medium | Sub-cent padding passed a limit check. | Reject >2 decimal places. | `test_sub_cent_padding_cannot_slip_under_the_limit` |
| F11 | Input | Unbounded `arguments` payload. | Low | Trace bloat. | 16 KiB cap. | `test_oversized_arguments_are_rejected` |
| F12 | Grants | Grant claims carried `agent_id` but it was not checked at execute. | Medium | Audience unchecked. | `GRANT_AUDIENCE_MISMATCH` check, independent of envelope binding. | `test_grant_audience_is_enforced_even_if_identity_binding_passed` |

Concurrency was verified, not assumed: eight threads racing one grant through
the real app produce exactly one `execution_completed` and one ledger row
(`TestConcurrentGrantConsumption`), and the SQLite conditional `UPDATE` is
single-winner on its own without the service lock.

## Additions in v0.2.0 (MCP proxy, regression suites)

| # | Area | Finding | Severity | Handling | Test |
|---|---|---|---|---|---|
| F13 | Proxy | Truncating oversized arguments would let the upstream receive more than was authorized. | High | Refuse (`TOOL_ARGUMENTS_TOO_LARGE`) instead of truncate. | `_bounded` (proxy) |
| F14 | Proxy | Unmapped tools silently absent from evidence. | Low | Unmapped calls are sent as `mcp:unmapped` so the denial is on the trace; hidden from `tools/list` by default. | proxy e2e |
| F15 | Gateway | External executor could report outcomes for grants it does not hold, or repeatedly. | Medium | Outcome bound to grant audience, requires `execution_released`, accepted once. | `report_outcome`, proxy e2e |
| F16 | Regression | Recorded traces are untrusted input to the suite recorder. | Medium | Strict models (`extra="forbid"`, patterns, 16 KiB cap), chain/leaf consistency checks, provenance excerpts dropped, runner never executes. | `test_regression.py::TestRecording`, `TestFormatValidation` |
| F17 | Regression | A suite could try to select a policy set the operator did not intend. | Low | Suites and `--policy-set` run on an *ephemeral* gateway they own; they cannot affect a persistent gateway. | `run_suite` |

Open items added:

| # | Area | Finding | Severity | Mitigation |
|---|---|---|---|---|
| O13 | Proxy | Direct upstream access bypasses everything. | High if upstreams are reachable | Deployment requirement; see `docs/mcp-proxy.md`. |
| O14 | Proxy | The proxy is trusted code holding a bearer token. | High if the agent host is compromised | Host isolation, short credential TTLs, revocation. |
| O15 | Proxy | stdio only; no transport auth on the proxy's own stdio (the launching client is trusted by construction). | Medium | Streamable HTTP with client auth is roadmap. |
| O16 | Policy | No generic argument-constraint policy for arbitrary MCP tools; only capability + resource scope apply to `mcp.*`. | Medium | Roadmap item; today, scope resources narrowly. |

## Findings left open

| # | Area | Finding | Severity | Impact | Mitigation |
|---|---|---|---|---|---|
| O1 | Trust anchor | The operator key is omnipotent: it issues credentials for any agent, delegates all human authority, and reads everything. Whoever holds it is every human and every agent. | High (by design) | Compromise of the operator key is total compromise. | Split into roles (credential admin, human-authority signer, reader); represent humans with their own signed authority instead of the operator standing in for them. |
| O2 | Credentials | Bearer tokens: a stolen token is the agent until revoked or expired. No sender binding, no rotation protocol. | High | Token theft from an agent host = impersonation. | Short TTLs (supported), mTLS or DPoP-style proof of possession, rotation with overlap, per-host binding. |
| O3 | Tool bypass | Code with an in-process reference to a tool can call it without the gateway (`test_in_process_tool_call_is_not_protected` demonstrates this on purpose). | High if tools are co-located with agents | The boundary is the gateway process. | **Deployment requirement**: real tools accept calls only from the gateway (network policy, tool-side credentials held only by the gateway). See `docs/deployment.md`. |
| O4 | Gateway compromise | The gateway process and its SQLite file are the trust anchor; a DB-writer can mint grant records, rewrite chains, and produce a self-consistent forged trace. | High | Total. | Separate hardened service, least-privilege DB, asymmetric grant signing with KMS-held keys, external anchoring of chain heads. |
| O5 | Audit | Hash chain is tamper-evident only against edits that do not recompute the chain. | Medium | Insider forgery undetectable. | Anchor heads externally; write-only audit sink. |
| O6 | Grants | Symmetric HMAC; no `kid`; rotation invalidates all outstanding grants (TTL is 120 s, so the blast radius is small). | Low | Operational. | Ed25519 + `kid`. |
| O7 | Approval | `REQUIRE_APPROVAL` is recorded; there is no approver identity or approval endpoint. | Medium | Nothing can complete an approval today. | Signed approver decision → re-authorization → grant. |
| O8 | Availability | No rate limits or per-agent budgets; `/authorize` can be called in a loop. | Medium | Cost/DoS. | Budget constraints as delegation constraints; gateway rate limiting. |
| O9 | Validation errors | FastAPI 422 responses echo the offending input. An `execution_grant` sent in a malformed body would be echoed back to its own sender. | Low | Self-disclosure only. | Custom 422 handler that strips `input`. |
| O10 | Concurrency | A single in-process lock serialises state changes. Correct for one gateway; not a distributed guarantee. | Low (single node) | Multi-node deployments need a real DB transaction. | Postgres store implementations behind the same interfaces. |
| O11 | Human identity | Humans have no credential; the operator represents all of them. `envelope.principal` is verified against the chain root only. | Medium | Cannot distinguish which human is acting when several share a deployment. | Per-human signed root grants. |
| O12 | Time | Expiry checks trust the gateway clock. | Low | Skew. | NTP; explicit tolerance. |

## Checklist coverage

| Item | Result |
|---|---|
| Authentication and authorization confusion | Agent credential and operator key are distinct types, distinct headers, never interchangeable (`test_operator_key_alone_is_not_an_agent`). Fixed F1–F3. |
| Client-selectable authority or policy | Policy set: operator-only (F3). Authority: resolved server-side from grant id, chain root checked against `principal` (`test_forging_the_human_principal`). |
| Insecure defaults and exposed operator keys | F7, F8, F9. `.env` gitignored; `.env.example` has no values; keys never logged (grep of source: no key variable is ever formatted into a log call). |
| Direct tool bypass | O3, documented and demonstrated. |
| Action-envelope canonicalization | Sorted keys, fixed separators, UTF-8, Decimal/datetime/enum rendering; hash computed server-side from the parsed model on both calls, so client encoding differences cannot desynchronise it. NFC/NFD differences fail closed (hash mismatch). |
| Signed-grant scope and audience | `action_hash`, `trace_id`, `envelope_id`, `agent_id` (F12), `expires_at`, server record. No `kid` (O6). |
| Replay and concurrent grant consumption | Tested at app and store level. |
| Revocation race conditions | F6; delegation and credential revocation both re-checked under the execute lock. |
| Audit-chain integrity and tampering | Detected for naive edits at DB level (`_tamper_sqlite`); O5 for the rest. |
| Error responses leaking secrets | `test_error_messages_do_not_echo_credentials`, `test_secrets_never_appear_in_responses_or_traces`; O9. |
| Unsafe configuration for public deployment | F7, F8; `docs/deployment.md`. |
