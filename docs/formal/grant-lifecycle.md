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

## The grant token (`atp-grant/2`)

```
token  = b64url(header) "." b64url(canonical claims) "." b64url(sig)
header = {"alg": "EdDSA", "kid": kid, "v": "atp-grant/2"}
sig    = Ed25519_sign(sk[kid], b64url(header) "." b64url(claims))
kid    = hex(SHA-256(raw 32-byte public key))[0:16]
claims = [grant_id, trace_id, decision_id, envelope_id, action_hash,
          agent_id, policy_set_version, issued_at, expires_at]

Keys   == [active ∈ Kid, retired : Kid → Time]     \* retired[k] = when k stopped signing
Trusted(k, now) == k = active ∨ (k ∈ DOMAIN retired ∧ now < retired[k] + ttl)

verify(token, now) ==
  token has exactly three base64url segments, each the canonical encoding
  ∧ header = {"alg": "EdDSA", "kid": k, "v": "atp-grant/2"} exactly
  ∧ Trusted(k, now)                    \* unknown or expired-out kid → GRANT_SIGNATURE_INVALID
  ∧ Ed25519_verify(pk[k], sig, b64url(header) "." b64url(claims))
  ∧ claims re-encode canonically to the signed bytes
```

Only `active` has a private key; `Rotate` (`atp keygen --rotate`) makes a new
`active`, records `retired[old] := now` (the `grant-<kid>.retired` file) and
deletes the old private key. Because every grant expires at most `ttl` after
it was minted, and the old key minted nothing after `retired[old]`, every grant
the old key signed is expired or verifiable until `retired[old] + ttl`: rotation
never invalidates a live grant, and after one TTL the old key is inert. An
`atp-grant/1` (HMAC) token has two segments and is `GRANT_MALFORMED`.

```
Rotate: retired := retired ∪ {active ↦ now}; active := fresh kid
```

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
        ELSE IF token malformed / atp-grant/1        → blocked(GRANT_MALFORMED)
        ELSE IF ¬verify(token, now)                  → blocked(GRANT_SIGNATURE_INVALID)
        ELSE IF now ≥ claims.expires_at              → blocked(GRANT_EXPIRED)
        ELSE IF claims.action_hash ≠ H(env)          → blocked(GRANT_ENVELOPE_MISMATCH)
        ELSE IF claims.agent ≠ caller.agent          → blocked(GRANT_AUDIENCE_MISMATCH)
        ELSE IF ¬chain_live(env.delegation_grant_id) → blocked(DELEGATION_*)
        ELSE IF g.status ≠ issued                    → blocked(GRANT_ALREADY_CONSUMED | GRANT_REVOKED)
        ELSE g.status := consumed;
             IF tool is internal THEN Ledger := Ledger ∘ <<H(env)>>; append execution_completed
             ELSE append execution_released         \* the trusted executor runs it and reports once
  POST  blocked ⇒ Grants unchanged ∧ Ledger unchanged

Rotate: see "The grant token"                    \* operator action; restart to load
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
| KeyBinding | a token verifies only under a trusted `kid`'s public key; an unknown `kid`, a swapped header, or a key that claims another `kid` is GRANT_SIGNATURE_INVALID | `test_grants.py` (`test_unknown_kid_is_signature_invalid`, `test_wrong_key_is_rejected`, `test_tampered_header_rejected`) |
| RotationSafety | after `Rotate` at time r, a grant from the old kid verifies while `now < r + ttl` and is GRANT_SIGNATURE_INVALID after | `test_old_kid_verifies_after_rotation`, `test_home_rotation_keeps_old_grants_valid_for_one_ttl` |

## What is deliberately *not* proven

- Exactly-once external side effects. After `execution_released` the
  executor may crash before or after the upstream acts; the gateway can
  prove "released once" and "outcome reported once", not what the
  upstream did (`docs/security/idempotency.md`).
- Multi-node atomicity. The lock is in-process; SQLite's conditional
  `UPDATE ... WHERE status='issued'` is single-winner on one file, and
  that is the extent of the guarantee.
- Rotation while the old process keeps running. A running gateway keeps its
  loaded signer until restart; grants it mints under the old kid after the
  rotation time stop verifying at `retired[old] + ttl`, which can be
  earlier than their own expiry. Restart promptly after `atp keygen --rotate`.
- Clock monotonicity. `Tick` is assumed non-negative; a clock that jumps
  backwards re-validates expired grants until it catches up (`O12`).
