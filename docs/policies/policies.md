# Declared policy sets

Policy sets decide whether an action that is *already inside delegated
authority* may proceed. They are versioned so a decision can be replayed
under another version and so a regression suite can pin the version it
expects.

Two kinds exist:

- **built-in** sets (`payments-v1`, `payments-v2`): Python classes for the
  accounts-payable demo; they show what an argument-aware policy looks like;
- **declared** sets: YAML, loaded from `.atp/policies.yaml` (or
  `--policies FILE`), for everyone else.

Every set — built-in or declared — *always* evaluates the three kernel
policies first: `delegation.valid`, `capability.required`,
`resource.scope`. A file cannot switch them off. Rules add constraints on
top.

## Format (version 1)

```yaml
version: 1
policy_sets:
  - version: notes-v1                 # [A-Za-z0-9._-], unique, not a built-in name
    description: notes assistant
    include: []                       # optional: [payments] adds the built-in payment policies
    rules:
      - id: short-notes               # unique within the set; shows up as rule.short-notes.v1
        applies_to: {tool: mcp.notes, action: write_note}   # exact match; action defaults to *
        kind: argument_max_length
        argument: text
        max_length: 2000
      - id: never-delete
        applies_to: {tool: mcp.notes, action: delete_note}
        kind: deny
```

### Rule kinds (all nine)

| kind | fields | denies with | passes when |
|---|---|---|---|
| `argument_max` | `argument`, `max` (decimal), `optional` | `ARGUMENT_EXCEEDS_LIMIT` | value ≤ max |
| `argument_min` | `argument`, `min`, `optional` | `ARGUMENT_BELOW_MINIMUM` | value ≥ min |
| `argument_allowed_values` | `argument`, `values` (≤ 500 scalars), `optional` | `ARGUMENT_NOT_ALLOWED` | value is one of the values, same type (`1` ≠ `true` ≠ `"1"`) |
| `argument_subset_of` | `argument`, `values` (≤ 500 scalars), `optional` | `ARGUMENT_NOT_ALLOWED` | every item of a list argument is one of the values, same exact-type comparison as `argument_allowed_values` (`1` ≠ `true` ≠ `"1"`); a scalar counts as a one-item list; an empty list passes; a dict, `null`, float or nested list (as the argument or an item) denies with `ARGUMENT_INVALID` |
| `argument_max_length` | `argument`, `max_length`, `optional` | `ARGUMENT_TOO_LONG` | string/list/dict length ≤ max |
| `argument_required` | `arguments` | `ARGUMENT_MISSING` | every listed argument present and not `null` (an explicit `null` counts as missing) |
| `argument_forbidden` | `arguments` | `ARGUMENT_FORBIDDEN` | none of the listed arguments present (an explicit `null` counts as present, so it denies) |
| `deny` | — | `ACTION_DENIED_BY_POLICY` | never |
| `require_approval` | `approver_role` | `APPROVAL_REQUIRED_BY_POLICY` (REQUIRE_APPROVAL) | never; see limitations |

For example, `send_email` may only address known recipients (a denial reports
the allowed values and the offending items):

```yaml
- id: known-recipients
  applies_to: {tool: mcp.mail, action: send_email}
  kind: argument_subset_of
  argument: recipients
  values: [alice@example.com, bob@example.com]
```

Numeric rules parse the argument as a `Decimal` from its string form;
booleans, NaN, infinity and non-numbers fail closed with
`ARGUMENT_INVALID`. An `argument_*` rule whose argument is absent denies
with `ARGUMENT_MISSING` unless `optional: true`. With `optional: true`, an
argument sent as an explicit `null` counts as absent and passes; without it,
`null` is still checked (and denied) like any other value. `optional` never
loosens a present value: an out-of-bounds value denies either way.
`argument_required` treats an explicit `null` as missing (denies with
`ARGUMENT_MISSING`); `argument_forbidden` treats it as present (denies with
`ARGUMENT_FORBIDDEN`).

### What the format deliberately does not have

No expressions, no regular expressions, no globbing, no references between
rules, no time-of-day, no cumulative budgets. Each is either unsafe as
untrusted input (regex), or better served by a real policy engine behind
the adapter boundary (`why-not-just-opa.md`), or not yet designed
correctly (budgets: `../security/threat-model.md`, non-goals).

Limits: 200 rules per set, 500 allowed values per rule, 1 MiB per file.

## How rules are evaluated

The engine evaluates every applicable policy in file order after the kernel
policies, records every result (pass or fail, with the compared values) in
the decision, and reduces: first DENY wins; else first REQUIRE_APPROVAL;
else ALLOW. `atp policy explain` prints exactly those records.

## Tools you can reason about

- `atp policy explain TRACE` — why, which constraint, what would need to change.
- `atp policy diff A B` — structural diff of two sets.
- `atp policy impact --from A --to B` — decisions that flip on recorded actions.
- `atp policy coverage` — per recorded action, which argument names any
  rule constrains and which are unguarded. No score.
- `atp mutate TRACE` — perturb a recorded action and see what the set decides.

## Budgets: cumulative spend per period

Rules look at one action. A **budget** limits the total spent under a
delegation over a calendar period. It is a constraint on a grant, not a
rule in a policy set, so it applies under every policy set:

```yaml
# atp-mcp.yaml (local mode): delegated to the session agent
version: 1
server_name: bank
upstream: {command: uv, args: [run, bank-mcp]}
authority:
  capabilities: [bank:send]
  resource_scope: ["acct:*"]
  budget:
    amount: {amount: "500.00", currency: USD}
    period: day                     # day | week | month
```

In serve mode, put it in `constraints` on any grant in a chain
(`POST /delegations`):

```json
{"constraints": {"max_amount": {"amount": "1000", "currency": "USD"},
                 "budget": {"amount": {"amount": "5000", "currency": "USD"},
                            "period": "week"}}}
```

- **Periods** are UTC calendar periods: a `day` starts at 00:00 UTC, a
  `week` at 00:00 UTC on **Monday** (ISO 8601), a `month` at 00:00 UTC on
  the 1st. Spend counts in the period in which it was authorized. A new
  period starts from zero; nothing carries over.
- **Which actions count:** any action whose `arguments` carry an `amount`
  (for the built-in payments tool, every payment). `currency` defaults to
  the budget's currency when the arguments have none. An action without an
  `amount` argument is not budgeted.
- **Currency:** a budget is in one currency. An action in another currency
  under a budgeted chain is denied with `PAYMENT_CURRENCY_NOT_PERMITTED`;
  there is no conversion.
- **Chains:** every budget on the chain applies, each on its own. The
  tightest one binds, and budgets with different periods (a daily and a
  monthly) are checked independently. Spend is counted per (root human,
  grantee of the grant that sets the budget), so a budget on an
  orchestrator's grant also counts its sub-agents' spend, and a budget in
  `atp-mcp.yaml` keeps counting across `atp mcp wrap` sessions.
- **Lifecycle:** `authorize` *reserves* the amount when it mints the
  execution grant, atomically (SQLite `BEGIN IMMEDIATE` plus a sum check;
  two concurrent authorizations, even from two gateways on one file,
  cannot together exceed the budget). A completed execution *settles* the
  reservation into spend; a failed one *releases* it. A reservation whose
  grant expires without an execution or an outcome report is released
  lazily, on the next reservation and whenever traces are listed
  (`atp trace list`, `GET /traces`). An outcome reported after that still
  settles: money that was spent counts.
- **Over budget** is DENY `PAYMENT_EXCEEDS_BUDGET` from
  `gateway.budget.v1`. `atp policy explain` shows the binding budget's
  `limit`, `spent`, `reserved` and `requested`, and the grant that sets it.
- **Approvals do not lift budgets.** An over-budget action is denied before
  it is put to an approver, and an approved retry that no longer fits (other
  spend landed meanwhile) is denied without using up the approval.
- **Replay** re-evaluates policy only; it does not re-check budgets, which
  depend on what else was spent at the time.

## Where sets come from at run time

| Command | Sets available |
|---|---|
| `atp mcp wrap` | built-ins + `<home>/policies.yaml`; default is `policy_set` from `atp-mcp.yaml` |
| `atp test SUITE` | built-ins + the suite's `policies:` file (relative to the suite), else `--policies`, else `<home>/policies.yaml` |
| `atp serve` | built-ins + `ATP_POLICY_FILE` |

A declared version may not shadow a built-in name; loading fails loudly.

## Limitations

- `require_approval` routes the action to a human; see `approvals.md`.
- Rules see the envelope's `tool`/`action`/`arguments` only, not the
  upstream tool schema or result.
- No rule can widen authority: a set with zero rules still enforces
  delegation, capability and scope.
