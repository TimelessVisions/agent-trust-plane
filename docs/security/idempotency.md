# Idempotency, partial failure, and what the trace can prove

Single-use grants guarantee **at most one release per authorized action**.
They do not guarantee that the external side effect happened exactly once.
This page states precisely what ATP proves after each failure and what it
cannot.

## Two different "once"s

| Statement | Who guarantees it | ATP proves it? |
|---|---|---|
| The grant was consumed once | gateway (atomic `issued → consumed`) | Yes: `grant_issued`, `execution_released`/`execution_completed` on the trace; state machine checked exhaustively |
| The upstream performed the effect once | the upstream | No. ATP records what the executor *reported* |

Exactly-once external effects need cooperation from the tool: an
idempotency key the tool honours, or an effect that is naturally
idempotent (`write_file` with full content is; `append` is not; `send
payment` is not).

## Idempotency key

Every grant has a `grant_id`; the envelope has an `envelope_id`; both are
unique and recorded. A tool that accepts an idempotency key should be given
the `grant_id`. The proxy does **not** inject it into arguments (the
arguments are hashed and the upstream schema is unknown); a mapping-level
option to do so is on the roadmap. Until then, the guidance is: for
non-idempotent tools, treat "released but no outcome" as "unknown", not as
"did not happen".

## Failure matrix (MCP proxy path)

Sequence: client → proxy: authorize (gateway) → execute/release (gateway) →
call upstream → report outcome (gateway) → return to client.

| Failure point | Grant state | Trace shows | Upstream effect | What a reviewer can conclude |
|---|---|---|---|---|
| Gateway down at authorize | none | nothing (no trace) | none | call refused; nothing happened |
| Gateway down between authorize and execute | issued, unconsumed | `decision_made`, `grant_issued` | none | nothing happened; the grant expires (TTL 120 s) |
| Proxy crashes after release, before upstream call | consumed | `execution_released`, no outcome | none | released but not performed; **cannot be distinguished from the next row by the trace alone** |
| Proxy crashes after upstream call, before outcome report | consumed | `execution_released`, no outcome | happened | see above; only the upstream knows |
| Upstream timeout (`request_timeout_seconds`) | consumed | `execution_failed` (reported_by executor, error text) | unknown (may have completed after the timeout) | treat as unknown |
| Upstream returns `isError` | consumed | `execution_failed` with the summary | probably none (tool-defined) | the tool said it failed |
| Outcome report rejected (gateway restarted with new keys, credential revoked meanwhile) | consumed | `execution_released` only | happened | same as proxy crash after call |
| Client retries the same tool call | new envelope, new grant | second trace | may happen twice | ATP does not deduplicate client retries; each call is a new action |
| Duplicate outcome report | consumed | first accepted; second `EXECUTION_OUTCOME_ALREADY_REPORTED` | — | evidence stays single |
| Gateway SQLite locked/busy | depends | error to the proxy → call refused (`GatewayError`) | none | nothing happened |

`atp trace list` shows the last event per trace; a trace whose last event
is `execution_released` is the "unknown" case and should be reconciled
against the upstream.

## Shadow mode

Same matrix with `shadow_would_deny` in place of the grant rows; the
executor reports `shadow_execution_*`. A trace that ends at
`shadow_would_deny` means the proxy did not report; the effect is unknown.

## Chaos tests that exist

- Upstream error / `isError` result → `execution_failed` with summary
  (proxy e2e).
- Concurrent execution of one grant → exactly one side effect
  (`TestConcurrentGrantConsumption`, 8 threads).
- Revocation between authorize and execute → blocked (`test_execute_after_delegation_revoked_by_grantor`).
- Expiry between authorize and execute → blocked (state machine, stateful test).
- Gateway restart with a persistent store → grants and traces survive
  (`test_persistence`); with new keys → outstanding grants fail signature
  verification (documented O6).

## Chaos tests that do not exist yet

Proxy killed mid-call (needs a fault-injecting upstream), network partition
between proxy and a remote gateway, SQLite `database is locked` under a
second writer. These are listed in the roadmap; the matrix above is what
the design implies, not what was measured.
