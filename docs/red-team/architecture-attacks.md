# Architecture attacks (red-team pass, 2026-09-17)

Perspective: a hostile senior application-security engineer with the
source, a valid agent credential, control of every agent and every
document, and a copy of the CLI. Each attack lists what was tried, the
result, and the test that keeps it that way. "Residual" means the attack
works under some assumption and the assumption is documented.

Legend: **blocked** (test exists) · **residual** (documented gap) ·
**n/a** (not applicable to this design).

## Identity

| Attack | Result | Evidence |
|---|---|---|
| Impersonation: valid credential for A, envelope says B | blocked, recorded as `identity_rejected` | `TestImpersonation` |
| Token theft | residual: bearer; TTL + revocation | O2, `identity-providers.md` |
| Credential replay after revocation / expiry, incl. between HTTP auth and the lock | blocked | `test_revoked_credential_is_rechecked_under_the_lock`, `test_expired_credential` |
| Credential sharing between agents | blocked: one credential names one agent; envelope must match | `TestImpersonation` |
| Confused deputy: parent uses child's grant, child uses parent's | blocked | `test_orchestrator_cannot_use_ap_agents_grant`, EVAL-005 |
| Operator impersonation via agent token | blocked: separate header, constant-time compare | `test_operator_key_alone_is_not_an_agent` |
| Human-principal forgery | blocked (`DELEGATION_PRINCIPAL_MISMATCH`) | `test_forging_the_human_principal` |
| Stale identity (revoked between authorize and execute) | blocked | stateful property test |
| Credential enumeration | n/a: ids are 128-bit random; unknown id and wrong secret take the same path | `authenticate` dummy-hash compare |
| Timing leak on secret compare | blocked: `hmac.compare_digest` | `credentials.py` |
| Identity from the request body | blocked by construction: provider sees headers only | `test_alternative_provider_drives_binding` |

## Delegation

| Attack | Result | Evidence |
|---|---|---|
| Privilege escalation (child wider than parent on any dimension) | blocked | `test_delegation_invariants.py`, property `test_accepted_chains_never_widen` (200 random chains) |
| Parent/child inversion, forged parent id, cycle, truncation | blocked (`DELEGATION_CHAIN_BROKEN`, `_NOT_FOUND`, depth cap) | `test_delegation_invariants.py` |
| Stale grant (expired/revoked link anywhere in the chain) | blocked at authorize and again at execute | `test_expired_delegation`, `test_delegation_revoked_between_authorize_and_execute` |
| Resource wildcard abuse (`*` in ids, prefix child wider than parent) | blocked: grammar forbids stray `*`; `covers` is sound | `test_validate_pattern_rejects_misplaced_wildcards`, `test_covers_is_sound` |
| Scope ambiguity (`path:/work*` vs `path:/worker`) | residual by design: prefix is textual; generator emits `dir/*` | documented in `scope.py`, `test_prefix_matches` |
| Currency mismatch / unit mismatch | blocked (`PAYMENT_CURRENCY_NOT_PERMITTED`; 2-dp money) | `test_sub_cent_padding_cannot_slip_under_the_limit` |
| Delegation after revocation | blocked (`DELEGATION_PARENT_INVALID`) | `test_delegation_invariants.py` |
| TOCTOU between resolve and consume | blocked: revoke and execute share the lock | `revoke_delegation` under `_lock` |

## Policy

| Attack | Result | Evidence |
|---|---|---|
| Caller-selected policy / downgrade | blocked: operator-only override | `TestPolicySelection` |
| Malformed arguments, unexpected fields (payments) | blocked (`extra=forbid`) | `test_unexpected_argument_rejected` |
| Unicode confusion in resources | residual: no normalisation beyond NFC-agnostic byte compare; hash mismatch fails closed on both calls | review checklist |
| Path normalisation (`..`, `//`, backslashes, drive letters) | blocked | `TestPathNormalization` |
| Case normalisation | residual (O17): `casefold` must match the upstream FS | `test_casefold` |
| Float/decimal edge cases (`1000.004`, NaN, inf, bool-as-int) | blocked | money tests, `test_numeric_max_with_optional_argument`, `test_allowed_values_are_type_strict` |
| Wildcards in declared `applies_to` | limited to `*` = any; no globbing | `AppliesTo` |
| Default allow | n/a: an empty declared set still enforces the kernel policies | `test_suite_cannot_switch_off_kernel_policies_via_policy_file` |
| Policy conflict / order dependence | first DENY wins deterministically; every evaluation recorded | `test_deterministic` |
| Missing policy set | blocked: gateway refuses to start; `POLICY_SET_NOT_FOUND` | `registry.py` |
| Partial evaluation (a policy raising) | fails closed with 500, no grant | `safe-defaults.md` |
| Huge input DoS (policy file, suite, config, bundle) | blocked: 1 MiB cap; 200 rules; 500 values; 16 KiB arguments | F20 |
| Regex DoS | n/a: the format has no regex | `policies.md` |

## Execution grants

| Attack | Result | Evidence |
|---|---|---|
| Forged / modified token | blocked (HMAC, canonical re-encoding check) | `TestForgedGrants` |
| Modified action, target or arguments after authorization | blocked (`GRANT_ENVELOPE_MISMATCH`) | EVAL-007, stateful `execute_tampered` |
| Different agent | blocked (`GRANT_AUDIENCE_MISMATCH` + identity binding) | `test_grant_audience_is_enforced_*` |
| Different tool / policy | n/a: both are inside the hashed action fields / claims | `action_fields()` |
| Duplicate and concurrent execution | blocked; 8-thread race → 1 side effect | `TestConcurrentGrantConsumption`, exhaustive state machine |
| Expired token; revoked authority after authorization | blocked | state machine, stateful test |
| Server restart | grants persist (SQLite); after key rotation, signatures fail | `test_persistence`, O6 |
| Signature algorithm confusion | n/a: fixed HMAC-SHA256, versioned format `atp-grant/1` | `grants.py` |
| Audience confusion across gateways | blocked: record must exist locally | `test_grant_from_another_gateway_instance_is_unknown` |
| Nonce collision | n/a: 128-bit random ids; store rejects unknown ids | — |
| Revoke overwriting a consumed record | **found and fixed** (F18) | `test_grant_state_machine.py` |

## MCP

| Attack | Result | Evidence |
|---|---|---|
| Direct upstream bypass | residual: deployment requirement | `test_direct_upstream_access_is_not_protected`, `enforcing-the-boundary.md` |
| Malicious tool descriptions / annotations | annotations only suggest capability names in a file the human reviews; descriptions cleaned; `destroy` never delegated | `discovery.py`, O21 |
| Malicious tool result | bounded preview recorded; result passed through unchanged to the client (as any proxy would) | `_summarise` |
| `tools/list` inconsistency (server adds a tool later) | new tool is unmapped → denied and hidden | proxy e2e |
| Tool name collision | n/a: one upstream per proxy; config rejects duplicate mappings | `test_duplicate_tool_mappings_rejected` |
| Transport downgrade | plain `http://` only to localhost | `test_plain_http_only_on_localhost` |
| Malformed MCP messages | handled by the SDK; the proxy sees typed params only | SDK |
| Oversized payload | refused, never truncated | `_bounded`, F13 |
| Cancellation / progress notifications | not proxied; a cancelled upstream call surfaces as `UPSTREAM_ERROR` and `execution_failed` | limitation |
| Server crash / timeout | `UPSTREAM_ERROR`, `execution_failed`; effect unknown | `idempotency.md` |
| Proxy crash after upstream execution | residual: `execution_released` without outcome | `idempotency.md` |
| Retries causing duplicate effects | each retry is a new authorized action; not deduplicated | `idempotency.md` |
| Upstream mutating the tool after authorization | n/a: the upstream is trusted to execute what it is told; ATP cannot verify | non-goal |
| Path traversal | blocked in the resource; the raw argument is forwarded unchanged (same file) | `test_traversal_leaves_scope` |

## Audit

| Attack | Result | Evidence |
|---|---|---|
| Event deletion / insertion / reordering / modification by a non-writer | detected | `test_tampering_is_detected`, `TestTraceIntegrity` |
| Recomputed chain by a DB writer | residual (O5) | `trace-integrity.md` |
| Trace ownership attack | blocked | `test_agent_cannot_append_to_another_agents_trace` |
| Secret leakage into traces/bundles/responses | blocked | `test_secrets_never_appear_in_responses_or_traces`, `test_bundle_never_contains_tokens_or_keys` |
| Oversized provenance | blocked by field caps | envelope model |
| PII exposure | residual by design; `privacy.md` | — |

## Replay

| Attack | Result | Evidence |
|---|---|---|
| Replay triggering execution | blocked by construction | `test_replay_never_executes`, stateful `replay_latest` |
| Replay reading current instead of recorded authority | blocked: authority snapshot from the decision | `_replay` |
| Caller-controlled policy on replay | operator-only route | `TestPolicySelection` |
| Untrusted trace injection into `regression add` / `mutate` | strict models; hostile-trace tests | `TestRecording` |
| Stale schema | suite `version: 1` is the only accepted value; bundles carry `bundle_version` | `regression/schema-versioning.md` |

## CI / regression

| Attack | Result | Evidence |
|---|---|---|
| Malicious YAML (code execution, aliases) | `safe_load` only; 1 MiB cap | F20 tests |
| Path traversal via `policies:` | file must exist and parse as a policy file; contents never echoed | `test_suite_policies_path_outside_tree_is_rejected_without_leak` |
| Unsafe deserialization | n/a: pydantic models only | — |
| Environment secret leakage | the runner uses an ephemeral gateway with generated keys; `.env` is not read | `ephemeral_settings` |
| False PASS due to an ignored policy set | the report names the set it ran under; an unknown set is an error, not a pass | `format_text` |
| Baseline tampering / changed expectation hiding a regression | residual by design: a suite is code; review it in PRs like a test | `regression-testing.md` |

## Dashboard

| Attack | Result | Evidence |
|---|---|---|
| XSS via trace content | React text rendering, no `dangerouslySetInnerHTML` | grep |
| CSRF | n/a: no cookies; key in a header | — |
| Operator-key storage | module variable, not `localStorage` | `lib/api.ts` |
| Untrusted markdown | none rendered | — |
| Unsafe query parameters | trace id is fetched by id only; API validates | — |

## Fixed in this pass

F18 (absorbing grant states), F19 (hostile tool metadata), F20 (bounded
file reads), plus the missing controls F21 (path scopes) and F22 (shadow
mode) that the pre-mortem required. Nothing High was found in the kernel;
the High items remain the documented deployment assumptions (O3/O13) and
the trust anchors (O1/O4).
