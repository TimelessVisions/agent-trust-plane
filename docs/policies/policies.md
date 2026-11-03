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
| `argument_required` | `arguments` | `ARGUMENT_MISSING` | every listed argument present |
| `argument_forbidden` | `arguments` | `ARGUMENT_FORBIDDEN` | none of the listed arguments present |
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
`null` is still checked (and denied) like any other value.

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

## Where sets come from at run time

| Command | Sets available |
|---|---|
| `atp mcp wrap` | built-ins + `<home>/policies.yaml`; default is `policy_set` from `atp-mcp.yaml` |
| `atp test SUITE` | built-ins + the suite's `policies:` file (relative to the suite), else `--policies`, else `<home>/policies.yaml` |
| `atp serve` | built-ins + `ATP_POLICY_FILE` |

A declared version may not shadow a built-in name; loading fails loudly.

## Limitations

- `require_approval` records the requirement; there is no approver
  endpoint in this release (`../security/threat-model.md`, O7).
- Rules see the envelope's `tool`/`action`/`arguments` only, not the
  upstream tool schema or result.
- No rule can widen authority: a set with zero rules still enforces
  delegation, capability and scope.
