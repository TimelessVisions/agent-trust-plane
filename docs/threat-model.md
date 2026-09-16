# Threat model

This document states what Agent Trust Plane defends against **today**, what it
does not, and what it would take to close each gap. It is written to be
checked against the code and the eval suite, not to reassure.

## Assets

- **Money and side effects**: anything a tool does in the world (the demo's
  payments ledger stands in for a real rail).
- **Authority**: the delegation grants that say who may do what.
- **The audit trail**: the ability to reconstruct, after the fact, what
  happened and why.

## Trust boundaries

```
untrusted                      |  trusted (MVP)
-------------------------------+----------------------------------------
model outputs                  |  gateway process
retrieved content (invoices,   |  gateway SQLite file
  email, web, tool output)     |  grant signing key
agent code and its claims      |  policy set code
the delegation graph AS        |  vendor directory
  ASSERTED by an agent         |
```

Everything on the left is input. Nothing on the left is believed without
being checked against something on the right.

## Attacker model

An attacker can:

- author any content an agent will read (indirect prompt injection);
- fully control one or more agents (a "compromised agent"), including making
  arbitrary HTTP calls to the gateway with arbitrary envelopes and tokens;
- observe tokens returned to a compromised agent and replay or edit them;
- try to create delegations through the API.

An attacker in the MVP model **cannot**:

- read or write the gateway's database or process memory;
- obtain the grant signing key;
- change policy set code.

The section "Not yet handled" covers what happens when those assumptions fail.

---

## Threats handled in the MVP

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
| **Replay used to execute** | Use `/replay` as a back door to run an action. | Replay re-evaluates only; it never mints grants or touches tools. | `test_replay_under_hardened_policy_flips_a_missed_attack` (ledger unchanged) |

---

## Threats NOT yet handled

Stated plainly. Each has a sketch of what closing it would take.

| Threat | Current state | What it would take |
|---|---|---|
| **Agent identity spoofing** | The gateway does **not authenticate callers**. `envelope.agent` is asserted by whoever sends the request. A caller who knows a grant id and the grantee's id can act as that grantee. | Per-agent credentials (mTLS, signed envelopes with per-agent keys, or workload identity), and binding `envelope.agent` to the authenticated identity. This is the single most important gap. |
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

## Residual risk summary

The MVP proves that **authority can be bounded, decisions can be explained,
and execution can be bound to decisions** in a way that survives a fully
compromised agent. It does not yet prove that the gateway itself is a hardened
trust anchor, and it does not authenticate agents. Anyone evaluating this for
real use should read the second table first.
