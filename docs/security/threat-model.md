# Threat model (v0.3.0)

Written to be checked against the code and the test suite, for a reader who
assumes nothing. Every "handled" row names a mechanism and a test. Every
gap is stated as a gap.

## Assets

1. **Side effects in the world** — files written, payments sent, tickets
   changed. The demo ledger stands in for a real rail.
2. **Authority** — the delegation graph that says who may do what, and
   the operator key that roots it.
3. **Evidence** — the ability to reconstruct, after the fact, what was
   proposed, decided, executed and why.
4. **Keys and credentials** — grant signing key, operator key, agent
   bearer secrets, upstream secrets held by the proxy.

## Actors

| Actor | Trust | Holds |
|---|---|---|
| Human principal | authority source; represented by the operator in this release | nothing directly |
| Operator | fully trusted; the trust anchor | operator key, `.atp/keys.env` |
| Agent (model + runtime) | **untrusted**; assumed compromised by injection at any time | its own bearer credential |
| MCP client (IDE, host app) | trusted to launch the proxy; not trusted for authority | the proxy's stdio |
| ATP proxy / executor | trusted code; holds an agent credential and the upstream session | agent token, upstream secrets from its config |
| Gateway process + store | trusted; the boundary | signing key, operator key, all records |
| Upstream MCP server / tool | untrusted for metadata and results; trusted to perform what it is told | its own state |
| External content (documents, web, tool output) | untrusted | — |
| Attacker | controls any agent, any content, the network path to the gateway; can replay/edit anything an agent sees | agent-level credentials |

## Trust boundaries

```
untrusted                              |  trusted
---------------------------------------+---------------------------------------
model output, prompts, retrieved docs  |  gateway process and its SQLite store
tool descriptions, annotations, results|  grant signing key, operator key
MCP client requests (name, arguments)  |  policy sets (built-in code, declared file)
the envelope (every field)             |  the proxy process and its config
agent bearer credential (can be stolen)|  the deployment boundary (docs/security/enforcing-the-boundary.md)
traces imported from elsewhere         |  the operator's machine (`.atp/`)
regression suites, policy files (as    |
  files: parsed strictly, never run)   |
```

## Attack surfaces

`POST /authorize`, `/execute`, `/executions/{grant}/outcome`,
`/traces/{id}/events`, `/traces/{id}/shadow-outcome`, `/delegations*`
(agent-authenticated); operator routes; the proxy's stdio (`tools/list`,
`tools/call`); the upstream connection (stdio child or Streamable HTTP);
files read by the CLI (`atp-mcp.yaml`, `policies.yaml`, suites, bundles);
the dashboard (operator key in browser memory).

## Attacker model

An attacker can: author any content an agent reads; fully control one or
more agents including their valid credentials; observe and replay
anything returned to those agents; craft any MCP message to the proxy;
craft any file the CLI reads.

An attacker in this model **cannot**: write the gateway's store or process
memory; obtain the signing or operator key; obtain another agent's
credential; change policy code or the policy file; reach the upstream
without the proxy (a deployment requirement, not a property). The
"unhandled" section says what happens when each of these assumptions
fails.

---

## Handled threats

Each row names the mechanism and the test or eval that exercises it.

| Threat | What happens | Mechanism | Evidence |
|---|---|---|---|
| **Indirect prompt injection** | Invoice content instructs the agent to pay $12,500 to an attacker account; the agent complies. | The agent's proposal is just a proposal. The gateway resolves the agent's *actual* authority ($1,000) and denies. The untrusted content is recorded with its hash. | EVAL-002; `test_gateway_api.py::TestPrimaryDemo` |
| **Evasive injection (under limit, redirected)** | Injection keeps the amount under the limit but changes the destination. | Approved-destination policy compares the requested account to the vendor directory. The baseline policy set misses it; the hardened set catches it; replay proves the difference. | EVAL-006; `test_policy_engine.py::test_destination_swap_*` |
| **Compromised agent** | An agent submits any envelope it likes. | Nothing in the envelope is trusted as authority. The grant id is looked up server-side; policies evaluate against the resolved chain. | EVAL-003, EVAL-005 |
| **Compromised child agent** | A read-only child tries to pay: under its own grant, under its parent's grant, or with no authorization at all. | Capability policy; grantee-mismatch check on resolution; execution requires a grant. | EVAL-005; `test_red_team.py::TestAuthorityBoundaries` |
| **Privilege escalation via delegation** | An agent tries to issue itself or a peer a wider grant. | Issuance is checked against the parent chain's *effective* authority (capabilities, scope, amount, currencies, expiry). | EVAL-003, EVAL-004; `test_delegation_invariants.py` |
| **Excessive delegation** | Orchestrator with $10k tries to delegate $50k. | Same issuance invariant. | EVAL-004 |
| **Tampered grant in the store** | A grant wider than its parent is written directly to the database. | Resolution intersects the whole chain; the wider grant yields no extra authority. | `test_tampered_store_cannot_widen_authority` |
| **Stale / expired authority** | The chain has an expired or revoked link. | Every link is checked for expiry and revocation at authorize **and again at execute**. | `test_expired_delegation`, `test_delegation_revoked_between_authorize_and_execute` |
| **Confused deputy (parent using child's grant, or vice-versa)** | A principal presents a grant issued to someone else. | Leaf grantee must equal `envelope.agent`; root must equal `envelope.principal`. | `test_orchestrator_cannot_use_ap_agents_grant` |
| **Direct execution bypass** | Call `/execute` without `/authorize`. | Execution requires a signed grant; none → `GRANT_MISSING`. | EVAL-005 (c); `TestDirectExecutionBypass` |
| **Client-asserted authorization** | Envelope contains `"authorized": true`. | `extra="forbid"` on the envelope and request schemas → 422. | `test_client_asserted_authorized_flag_is_rejected` |
| **Forged authorization response / grant** | Attacker constructs a well-formed grant with their own key, or edits a real one. | HMAC-SHA256 with constant-time comparison; canonical re-encoding check. | `TestForgedGrants` |
| **Modified action after authorization (TOCTOU)** | Authorize $480, execute $12,500 with the same grant. | Grant carries the SHA-256 of the action-defining envelope fields; mismatch blocks. | EVAL-007; `TestModifiedActionAfterAuthorization` |
| **Replayed execution grant** | Use one grant twice. | Server-side record transitions `issued → consumed` via a conditional UPDATE; second use blocks. | EVAL-008; `test_grant_cannot_be_used_twice` |
| **Held grant used later** | Keep a grant and use it after the situation changed. | Short TTL (default 120 s). | `test_grant_expires` |
| **Grant with valid signature but no record** | Token from before a database reset, or minted by another instance with the same key. | Signature alone is not enough; the record must exist. | `test_grant_from_another_gateway_instance_is_unknown` |
| **Resource mismatch** | Agent scoped to `vendor:*` targets `payroll:*`. | Resource-scope policy over the intersected scope. | `test_resource_mismatch` |
| **Malformed or smuggled arguments** | `override_limit: true`, non-numeric amounts. | Payment argument schema with `extra="forbid"`; every payment policy denies on invalid arguments. | `test_unexpected_argument_rejected` |
| **Naive audit tampering** | Edit or delete a stored trace event. | Per-trace hash chain; `GET /traces/{id}` recomputes and reports `integrity.valid=false` with the first bad sequence number. | `test_tampering_is_detected`, `TestTraceIntegrity` |
| **Agent selects a weaker policy set** | `/authorize?policy_set_version=payments-v1` from an agent. | Policy-set override requires the operator key (`X-ATP-Operator-Key`, constant-time compare); agents never hold it. | `TestPolicySelection` |
| **Sub-cent padding** | `amount: "1000.004"` rounds to the limit. | `Money` rejects more than two decimal places instead of rounding. | `test_sub_cent_padding_cannot_slip_under_the_limit` |
| **Trace bloat / oversized payloads** | Multi-megabyte `arguments`. | 16 KiB cap on canonical `arguments`; string length caps on every other field. | `test_oversized_arguments_are_rejected` |
| **Provenance spoofing** | Agent writes events as `actor: "gateway"` or writes gateway-only event types. | Reserved actor and reserved event types are rejected on the agent-writable endpoint. | `test_agent_cannot_write_events_as_the_gateway`, `test_agent_can_record_provenance_but_not_gateway_events` |
| **Agent impersonation (A claims to be B)** | Doc agent's valid credential, envelope names the AP agent. | Authenticated identity must equal `envelope.agent`; the attempt is recorded as `identity_rejected` against the real credential. | `TestImpersonation`, EVAL-005(c) |
| **Using another agent's delegation** | Doc agent names itself, presents the AP grant. | Chain leaf grantee must equal the authenticated agent. | `test_agent_a_using_agent_b_delegation_honestly`, EVAL-005(b) |
| **Stolen execution grant** | Doc agent presents a grant minted for the AP agent. | Identity binding on `/execute` plus grant audience (`agent_id` claim) check. | `test_execute_with_someone_elses_grant_token`, `test_grant_audience_is_enforced_*`, EVAL-008 |
| **Forged human principal** | Envelope claims to act for a different human than the chain root. | `DELEGATION_PRINCIPAL_MISMATCH`. | `test_forging_the_human_principal` |
| **Forged human authority via delegation** | Agent issues a grant with a human grantor. | Human grantors require the operator key. | `test_forging_human_authority_via_delegation`, EVAL-003(c) |
| **Forged audit actor** | Agent writes provenance as another agent or as the gateway. | No actor field; actor = authenticated agent; gateway-only event types rejected. | `test_forging_audit_actor` |
| **Trace pollution** | Agent appends to another agent's trace. | Trace ownership by first writer. | `test_agent_cannot_append_to_another_agents_trace` |
| **Revoked / expired credential** | Continue using a revoked token; use an expired one. | Checked at the HTTP layer and again under the execute lock. | `test_revoked_credential`, `test_expired_credential`, `test_revoked_credential_is_rechecked_under_the_lock` |
| **Unauthenticated execution / provenance** | No `Authorization` header. | 401 with `WWW-Authenticate: Bearer`; nothing written. | `test_execute_without_identity`, `test_unauthenticated_provenance_is_rejected` |
| **Concurrent execution of one grant** | Eight simultaneous `/execute` calls with the same grant. | Conditional UPDATE `issued → consumed`; single winner verified at app and store level. | `TestConcurrentGrantConsumption` |
| **Anonymous reads of decisions and accounts** | `GET /traces`, `/ledger/payments` from the network. | Operator key required for all reads except `/health` and `/policy-sets`. | `test_reads_are_operator_only` |
| **MCP tool call outside delegated authority** | A client behind the proxy calls a mapped tool on a resource outside its scope, or an unmapped tool. | Every `tools/call` is an envelope decided by the gateway; unmapped tools map to the never-delegated `mcp:unmapped` capability and are hidden from `tools/list`. | `test_proxy_forwards_allowed_calls_and_blocks_unmapped_ones`, `test_proxy_enforces_argument_derived_resource_scope` |
| **Argument tampering between authorize and forward (proxy)** | The proxy could forward different arguments than it hashed. | The proxy forwards exactly the arguments in the envelope and refuses oversized arguments rather than truncating. | `_bounded` in `proxy.py`; e2e tests |
| **Forged or duplicate execution outcome** | An executor reports an outcome for a grant it does not hold, or twice. | `/executions/{grant}/outcome` requires the grant's audience credential, a prior `execution_released`, and accepts one report. | `report_outcome` in `service.py`; proxy e2e trace shape |
| **Replay used to execute** | Use `/replay` as a back door to run an action. | Replay re-evaluates only; it never mints grants or touches tools. | `test_replay_under_hardened_policy_flips_a_missed_attack` (ledger unchanged) |

---
| **Path traversal past a directory scope (MCP)** | `write_file` to `/work/../etc/passwd` under scope `path:/work/*`. | Path normalisation before the resource string is built (`..`, separators, optional case folding); relative paths refused without a base. | `test_mapping.py::TestPathNormalization`, prefix-scope tests |
| **Wildcard smuggling in a resource** | Argument value `*` or `a*` to match a wider scope. | Concrete resources may not contain `*` anywhere; patterns allow it only in the defined positions. | `test_wildcard_in_derived_resource_is_refused`, `test_validate_pattern_rejects_misplaced_wildcards` |
| **Shadow/enforce confusion** | A caller asks for shadow mode, or a shadow denial is mistaken for a block. | Mode is a gateway setting; not an envelope or query field; every decision carries `enforcement`; traces record `shadow_would_deny` and `shadow_execution_*`; the CLI prints `WOULD_DENY`. | `test_shadow_mode.py`, wrap e2e |
| **Forged shadow outcome** | An agent reports that it executed a shadowed action on someone else's trace, or twice, or for an enforced denial. | Trace-owner bound; requires a recorded shadow denial; once. | `test_shadow_outcome_is_owner_bound_and_once`, `test_shadow_outcome_rejected_in_enforce_mode_and_for_allows` |
| **Policy file weakening the kernel** | A declared set tries to drop delegation/capability/scope checks or to replace `payments-v2`. | Kernel policies are always prepended; built-in names cannot be shadowed; unknown keys rejected; 1 MiB cap; safe YAML only. | `test_declarative.py`, `test_suite_cannot_switch_off_kernel_policies_via_policy_file`, `test_oversized_policy_file_refused_before_parsing` |
| **Offline analysis executing tools** | `atp test`, `policy impact`, `mutate` reach `/execute`. | They call only `/authorize` on an ephemeral gateway; a spy on `TrustPlane.execute` sees zero calls. | `test_no_execute_call_during_suite_impact_or_mutation` |
| **Hostile tool metadata** | Upstream tool names/descriptions with control characters, YAML syntax or spoofed annotations. | Names outside the MCP grammar are skipped (unmapped = denied); descriptions are cleaned and bounded; annotations only choose a *suggested* capability name that the human reviews; `destroy` is never delegated by the generator. | `discovery.py`, wrap e2e with the annotated notes server |
| **Evidence bundle tampering** | Edit a decision, an event, the order, or the head hash in an exported bundle. | Bundle hash + recomputed event chain; verification fails on each. | `test_tampered_bundle_fails_verification` |
| **Stray configuration overriding the local home** | A `.env` or `ATP_*` variable changes keys or mode for `atp mcp wrap`. | The home's `keys.env` and the explicit mode are passed as init values; `.env` is not read. | `test_home_is_authoritative_over_stray_env` |
| **Identity from the request body** | A provider that reads `envelope.agent`. | The provider protocol receives headers only; a second implementation is tested driving the same binding. | `test_alternative_provider_drives_binding` |


---

## Partially mitigated

Each row has a real mitigation and a real remaining gap.

| Threat | Mitigation in place | Remaining gap |
|---|---|---|
| **Agent credential theft** | Short TTLs, revocation re-checked under the lock, per-agent audience on grants | Bearer: a stolen token is the agent until revoked (`identity-providers.md`) |
| **Proxy host compromise** | The proxy cannot mint grants or forge decisions; unmapped tools stay denied | It can forward arbitrary calls to *its* upstream and holds upstream secrets from its config |
| **Audit tampering by a DB writer** | Hash chain detects naive edits; bundles verify offline | A writer can recompute a consistent history (`trace-integrity.md`) |
| **Partial execution failure** | At most one release per grant; outcomes reported once; `execution_released` without outcome is visible | External effect may have happened; no idempotency key injected (`idempotency.md`) |
| **Case-insensitive filesystems** | `casefold` option on path normalisation; init sets it on Windows | A wrong setting lets `/WORK` escape `path:/work/*`; symlinks are never resolved |
| **Malicious tool output** | Bounded preview recorded; never executed by ATP | Not labelled as untrusted content for the agent; no output policy |
| **Approval** | `REQUIRE_APPROVAL` recorded, no grant minted | No approver identity or endpoint (design in `../research/rejected-ideas.md`) |

## Unhandled threats

Stated plainly. Each has a sketch of what closing it would take.

| Threat | Current state | What it would take |
|---|---|---|
| **Direct upstream access (MCP)** | An agent launches or connects to the upstream MCP server without the proxy. | Not prevented. The proxy is the enforcement point; `test_direct_upstream_access_is_not_protected` shows the bypass. Deploy upstreams so only the proxy can reach them (`docs/security/deployment.md`, `docs/integrations/mcp-proxy.md`). |
| **Proxy host compromise** | The proxy holds the agent's bearer token and a live upstream session. | A compromised proxy can forward arbitrary calls to the upstream it launched; it cannot mint grants or forge gateway decisions. Same mitigation as credential theft: short TTLs, revocation, host isolation. |
| **Operator key compromise** | The operator key issues credentials for any agent, delegates all human authority and reads everything. It is the trust anchor; its holder is every human and every agent. | Split into roles; give humans their own signed authority; keep the key in a secret store and rotate it. |
| **Agent credential theft** | Bearer tokens are the agent until revoked or expired. There is no proof of possession, no sender binding, no rotation protocol. | Short TTLs (supported today), mTLS or DPoP-style proof of possession, per-host binding, rotation with overlap. |
| **Human identity** | Humans have no credential; the operator stands in for all of them, and `envelope.principal` is only checked against the chain root. | Per-human signed root grants. |
| **Gateway compromise** | If the gateway process or its SQLite file is attacker-writable, every guarantee falls: grants can be minted, chains rewritten, traces edited to look consistent. | Run the gateway as a separate hardened service; least-privilege DB credentials; asymmetric grant signing with the private key in an HSM/KMS so a DB-writer still cannot mint grants. |
| **Signing key exposure** | One symmetric key signs and verifies. Anyone with it can mint grants (they still need a server-side record, but a DB-writer can add one). | Ed25519 grants; key rotation with `kid` in the token; key in KMS. The token format is already versioned (`atp-grant/1`). |
| **Audit tampering by a DB-writer** | The hash chain is tamper-*evident* against naive edits only. An attacker who can rewrite the whole chain can produce a consistent forgery. | Anchor chain heads externally (append to a write-once log, a transparency log, or periodically sign heads with a key the gateway does not hold); write-only audit credentials; ship events to a separate sink. |
| **Approval workflow** | `REQUIRE_APPROVAL` is recorded and no grant is issued, but there is no approval endpoint or approver identity. | An approval record signed by an authenticated approver, referenced by a re-authorization that then mints the grant. |
| **Partial execution failure** | If a tool fails mid-way (`EXECUTION_FAILED`), the grant is already consumed and the failure is recorded, but there is no compensation, retry, or idempotency key passed to the tool. | Idempotency keys derived from `envelope_id`; tool-side saga/compensation hooks; explicit `retry` that re-authorizes. |
| **Malicious tool output** | Tool results are recorded in the trace but not sanitised or labelled before an agent reads them. Tool output is another injection vector. | Mark tool results as untrusted `ContentSource`s in provenance automatically; content policies on tool output. |
| **Rate limits, loops, cost explosions** | No per-agent rate limiting or budget accounting. An agent can call `/authorize` in a loop. | Per-grant and per-agent budgets as constraints (`max_actions`, `max_total_amount` per window) evaluated by policy; rate limiting at the gateway. |
| **Cross-request atomicity under concurrency** | A single in-process lock serialises authorize/execute. Fine for one gateway; not a distributed guarantee. | A real database with transactional consume; or a single-writer execution service. |
| **Policy engine as a target** | Policies are code in the trusted base. A bug is a bypass. | Policy tests per policy (present), property-based tests, and eventually a declarative policy format that can be reviewed independently of Python. |
| **Denial of service** | Not considered. | Standard service hardening. |
| **Human root compromise** | If the human's root grant is issued with excessive authority, everything below inherits the ceiling. | Out of scope for the control plane; organisational controls and small roots. |
| **Time** | Expiry checks trust the gateway clock. | NTP-disciplined hosts; tolerate small skew explicitly. |

---


---

## Deployment requirements

The guarantees above hold only when (full list: [deployment.md](deployment.md)):

1. Tools are reachable only through the gateway/proxy
   ([enforcing-the-boundary.md](enforcing-the-boundary.md)).
2. Keys are explicit, secret and rotated; `.atp/` is private to the
   operator.
3. Agents hold their own short-lived credentials; the operator key never
   reaches an agent host.
4. TLS in front of `atp serve`; `atp mcp wrap` is local by construction.
5. One gateway instance per store.

## Assumptions

- The gateway clock is roughly correct (NTP).
- Python, SQLite, `hmac`/`hashlib`, pydantic and the MCP SDK are not
  themselves compromised (supply chain: `docs/release/verification.md`).
- The operator reviews generated configs before relying on them:
  `atp mcp init` proposes, it does not decide.
- The upstream MCP server performs the call it is given and nothing else.

## Non-goals

- Detecting or filtering prompt injection in content. ATP bounds what an
  injected agent can *do*; it does not detect that it was injected.
- Sandboxing or isolating tools; secret management for tools; transports
  served with client auth; federation. Use a gateway.
- Exactly-once external side effects (`idempotency.md`).
- Distinguishing individual humans (the operator stands in for all).
- Data-loss prevention over trace contents (`privacy.md`).
- Rate limiting and budgets over time (designed, not built).

## Residual risk summary

v0.3.0 shows that authority can be bounded, decisions explained, execution
bound to decisions, agents told apart, policy changes measured against
recorded actions, and denials kept from silently returning — in a way that
survives a fully compromised agent holding its own valid credential. It
does not show that the gateway is a hardened trust anchor, and it
concentrates human authority in one operator key. Read the partial and
unhandled tables and the deployment requirements before relying on it.
