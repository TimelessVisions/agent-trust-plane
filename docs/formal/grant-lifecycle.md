# Execution-grant lifecycle: state-machine specification

This is the one protocol in Agent Trust Plane where a state-transition bug
would directly produce an unauthorized or duplicated side effect, so it is
specified precisely and checked exhaustively. No TLA+/Alloy toolchain was
available in the maintainer environment; the specification below is
written in the same style as a PlusCal model, and its properties are
checked by (a) an exhaustive enumeration of every operation sequence up to
length 5 against the two store implementations
(`services/gateway/tests/test_grant_state_machine.py`) and (b) a
Hypothesis stateful test that interleaves authorization, execution,
tampering, revocation, clock advance and replay through the real
`TrustPlane` (`services/gateway/tests/test_properties.py`).

## State

```
Grant     == [id, action_hash, agent, envelope_id, trace_id, expires_at,
              status ∈ {issued, consumed, revoked}]
Delegation == [id, revoked ∈ BOOLEAN, expires_at]
Credential == [id, agent, revoked ∈ BOOLEAN, expires_at]
Ledger    == sequence of action_hash            \* side effects that happened
Trace     == sequence of events per trace_id     \* append-only, hash-chained
now       ∈ Time
```

Initial: `Grants = {}`, `Ledger = <<>>`.

## Transitions

```
Authorize(env, caller):
  PRE   caller.credential live ∧ caller.agent = env.agent
        ∧ trace(env.trace_id) owned by env.agent or empty
  ACT   append action_proposed; resolve chain; evaluate policy → decision
        append policy_evaluated, decision_made(decision)
        IF decision.outcome = ALLOW THEN
          g := new Grant(status = issued, action_hash = H(env), agent = env.agent,
                         expires_at = now + ttl)
          Grants := Grants ∪ {g}; append grant_issued(g)
        ELSE IF mode = shadow THEN append shadow_would_deny
  POST  (∃ g ∈ Grants: g.trace = env.trace_id) ⇒ decision.outcome = ALLOW

Execute(env, token, caller):                     \* atomic under the service lock
  PRE   caller.credential live ∧ caller.agent = env.agent ∧ trace owned by env.agent
  ACT   append execution_attempted
        IF token = ⊥                                 → blocked(GRANT_MISSING)
        ELSE IF ¬verify(token)                       → blocked(GRANT_SIGNATURE_INVALID)
        ELSE IF now ≥ claims.expires_at              → blocked(GRANT_EXPIRED)
        ELSE IF claims.action_hash ≠ H(env)          → blocked(GRANT_ENVELOPE_MISMATCH)
        ELSE IF claims.agent ≠ caller.agent          → blocked(GRANT_AUDIENCE_MISMATCH)
        ELSE IF ¬chain_live(env.delegation_grant_id) → blocked(DELEGATION_*)
        ELSE IF g.status ≠ issued                    → blocked(GRANT_ALREADY_CONSUMED | GRANT_REVOKED)
        ELSE g.status := consumed;
             IF tool is internal THEN Ledger := Ledger ∘ <<H(env)>>; append execution_completed
             ELSE append execution_released         \* the trusted executor runs it and reports once
  POST  blocked ⇒ Grants unchanged ∧ Ledger unchanged

RevokeDelegation(d): d.revoked := TRUE            \* under the same lock as Execute
RevokeCredential(c): c.revoked := TRUE
Tick(δ): now := now + δ
Replay(trace, policy): append replay_performed    \* Grants and Ledger unchanged
ReportOutcome(g, caller): PRE g released ∧ caller.agent = g.agent ∧ no prior outcome for g
```

## Properties

| Name | Statement | Where checked |
|---|---|---|
| NoExecutionWithoutAuthorization | `∀ h ∈ Ledger: ∃ g ∈ Grants: g.action_hash = h ∧ g.status = consumed` | exhaustive, stateful |
| SingleUse | `∀ g: #{i : Ledger[i] = g.action_hash ∧ consumed via g} ≤ 1` | exhaustive (`consume` twice), stateful, `TestConcurrentGrantConsumption` (8 threads) |
| Exactness | a grant minted for `H(env)` never releases `env'` with `H(env') ≠ H(env)` | stateful `execute_tampered`, `test_grants.py` |
| AudienceBinding | a grant minted for agent A is never consumed by a caller ≠ A | `test_identity_security.py`, `test_grant_audience_is_enforced_even_if_identity_binding_passed` |
| RevocationLiveness | after `RevokeDelegation` (or credential revoke) no further `Ledger` append occurs for that chain | stateful (`revoked` flag), `test_execute_after_delegation_revoked_by_grantor`, `test_revoked_credential_is_rechecked_under_the_lock` |
| Expiry | `now ≥ expires_at ⇒ Execute is blocked` | exhaustive (`tick` op), `test_grants.py` |
| ReplaySafety | `Replay` leaves `Grants` and `Ledger` unchanged | stateful `replay_latest`, `test_replay_never_executes` |
| EvidencePrecedence | on every trace, `decision_made` precedes any `execution_*`; `grant_issued` precedes `execution_completed` | stateful invariant |
| Monotonic status | `issued → consumed`, `issued → revoked` are the only transitions; `consumed` and `revoked` are absorbing | exhaustive |
| ShadowNoGrant | in shadow mode a non-ALLOW decision mints no grant | `test_shadow_mode.py` |

## What is deliberately *not* proven

- Exactly-once external side effects. After `execution_released` the
  executor may crash before or after the upstream acts; the gateway can
  prove "released once" and "outcome reported once", not what the
  upstream did (`docs/security/idempotency.md`).
- Multi-node atomicity. The lock is in-process; SQLite's conditional
  `UPDATE ... WHERE status='issued'` is single-winner on one file, and
  that is the extent of the guarantee.
- Clock monotonicity. `Tick` is assumed non-negative; a clock that jumps
  backwards re-validates expired grants until it catches up (`O12`).
