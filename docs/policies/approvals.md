# Approvals: getting a REQUIRE_APPROVAL action executed

Some policies do not allow or deny an action outright; they route it to a
human. The payments threshold policy does this for payments above the
auto-approval threshold, and a declared rule can do it for any action:

```yaml
- id: writes-need-editor
  applies_to: {tool: mcp.notes, action: write_note}
  kind: require_approval
  approver_role: editor
```

The decision is `REQUIRE_APPROVAL` with `approval.approver_role`, no grant is
minted, and the trace records `approval_requested`.

## The flow

1. The agent proposes the action. The decision is `REQUIRE_APPROVAL`. Through
   the MCP proxy, the tool call fails with a message that names the trace and
   the command, for example
   `Needs editor approval on trace 3f2a9c1d0b7e: run atp approve 3f2a9c1d0b7e --as <approver-id>, then retry this exact call once.`
2. An approver decides:

   ```bash
   atp approve 3f2a9c1d0b7e --as alice                 # local ATP home (.atp/)
   atp approve 3f2a9c1d0b7e --as alice --deny          # a final no
   atp approve 3f2a9c1d0b7e --as alice --expires 1h    # default 15m, max 24h
   ATP_OPERATOR_KEY=... atp approve 3f2a9c1d0b7e --as alice --gateway https://atp.internal
   ```

   or over HTTP, with the operator key:

   ```http
   POST /approvals/3f2a9c1d0b7e
   X-ATP-Operator-Key: ...
   {"approver": {"id": "alice", "kind": "human"}, "decision": "approve", "expires_in": "15m"}
   ```

3. The agent retries the **identical** action: the same envelope, so the same
   trace and the same `action_hash`. The gateway finds the approval, mints one
   execution grant, and the action executes as usual. The MCP proxy does this
   for you: when the agent repeats the same tool call with the same
   arguments, the proxy re-sends the envelope it sent the first time.

## Who may approve

Approvers and their roles come from the operator-set `ATP_APPROVER_ROLES`
setting (environment, `.env` for `atp serve`, or the environment of
`atp approve` for a local home):

```bash
ATP_APPROVER_ROLES="human:alice=finance-manager,editor; human:bob=editor"
```

A bare id means `human:<id>`. The approver must hold exactly the role the
decision names; anyone else gets `APPROVER_ROLE_MISSING` (HTTP 403) and
nothing is recorded. The endpoint itself needs the operator key: in this
release the operator vouches for who the approver is (see the threat model,
"Approval workflow").

## What an approval binds

An approval is recorded in the `approvals` table and on the trace as
`approval_granted` or `approval_denied`, with:

`approval_id, trace_id, envelope_id, action_hash, decision_id, approver,
approver_role, decision, issued_at, expires_at, kid` and an Ed25519
signature by the active grant key over
`"atp-approval/1\n" + canonical_json(those fields)`. The domain prefix keeps
approval signatures and grant tokens from ever being interchangeable. After a
key rotation, an approval signed by the old key verifies for as long as the
old key does (one grant TTL).

## Rules

| situation on retry | outcome | reason code |
|---|---|---|
| valid, unexpired approval for this trace and action hash | ALLOW, one grant | `ALLOWED` |
| the action differs (e.g. a modified amount): different `action_hash` | unchanged, usually `REQUIRE_APPROVAL` | the policy's |
| the approval has expired | DENY | `APPROVAL_EXPIRED` |
| the approval was already used for a grant | DENY | `APPROVAL_ALREADY_USED` |
| the approver said no | DENY | `APPROVAL_DENIED` |
| the approval's role is not the one this decision needs | DENY | `APPROVER_ROLE_MISSING` |
| the stored approval does not verify | DENY | `APPROVAL_INVALID` |

On the approve call:

| situation | HTTP | reason code |
|---|---|---|
| the trace's decision is not REQUIRE_APPROVAL | 409 | `APPROVAL_NOT_REQUESTED` |
| the trace already has an approve or deny | 409 | `APPROVAL_ALREADY_DECIDED` |
| approver lacks the role | 403 | `APPROVER_ROLE_MISSING` |
| bad `expires_in` | 422 | `APPROVAL_INVALID` |

One decision per trace, and it is final. An approval is good for one grant:
the use is a conditional `UPDATE ... WHERE status = 'approved'` inside the
same transaction that issues the grant, so two concurrent identical retries
(even from two processes on one SQLite file) get one grant between them. The
grant itself is still single-use and short-lived, so an approval authorizes
at most one execution. Policy is re-evaluated on the retry: if the delegation
was revoked, or the action is now denied outright, the approval does not
help. Neither does an approval lift a budget: an approved retry that would
exceed a budget on the chain is DENY `PAYMENT_EXCEEDS_BUDGET`, and the
approval stays unused (`policies.md`, "Budgets").

## What the trace shows afterwards

A trace keeps its first decision as its headline. After an approved retry
executes, `atp trace list` and `GET /traces/{trace_id}` (`get_trace`) still
show `REQUIRE_APPROVAL`, the decision that opened the trace. The approval and
the ALLOW that followed it are in the trace's events: `approval_requested`,
`approval_granted`, then the retry's `decision_made` (ALLOW, with the
`approval_id`), `grant_issued` and the execution events.

## Denial and expiry are final for the trace

A denial (`--deny`) and an expired approval close the question for that
trace: retrying the identical envelope keeps returning `APPROVAL_DENIED` or
`APPROVAL_EXPIRED`, and the trace cannot be approved again
(`APPROVAL_ALREADY_DECIDED`). To try again, the agent makes the call afresh:
an identical tool call made as a new action gets a new trace id, so it opens
a new trace and, if policy still says so, a new approval request. Through the MCP proxy this happens on its own: the
proxy re-sends the original envelope only once, for the retry right after a
`REQUIRE_APPROVAL`; the call after a denial or expiry gets a new envelope and
trace.
