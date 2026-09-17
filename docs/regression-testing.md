# Security regression testing

A regression suite pins **authorization decisions**: for a declared
delegation graph and a set of actions, `atp test` asserts that the gateway
still returns the expected outcome and reason code under a chosen policy set.
It exists so that a policy change, a refactor, or a "helpful" widening of a
grant cannot silently re-allow something that was once caught.

## The loop

```
incident / eval / proxy trace  ──atp record──▶  case in suite.yaml  ──atp test──▶  exit 0 / 1 in CI
                                                       ▲
                                        edit expectation if the decision *should* change
```

## Commands

```bash
uv run atp test examples/regression-suite/accounts-payable.yaml           # human-readable, exit 0/1
uv run atp test suite.yaml --policy-set payments-v1                       # what would v1 have said?
uv run atp test suite.yaml --json results.json --junit results.xml        # machine-readable
uv run atp record --trace <id> --gateway http://127.0.0.1:8000 --suite suite.yaml --name "…"
```

`ATP_OPERATOR_KEY` (or `--operator-key`) is required for `record`, because
reading traces is an operator action.

Exit codes: `0` all decisions reproduced, `1` at least one changed, `2` the
suite could not be loaded.

## What a run does — and does not do

- Starts an **ephemeral, in-process gateway** (`:memory:`, per-run keys).
- Issues credentials for every agent principal in the suite and the grants in
  order (human grantors via the operator key, agent grantors via their own
  credential — the same rules as production).
- Calls `/authorize` once per case **and never `/execute`**. There are no side
  effects; the ledger of the ephemeral gateway stays empty and is discarded.
- Compares outcome, reason code and (if given) matched policy. On failure the
  explanation names the policy responsible, or "no policy matched" when an
  action that should have been denied was allowed.

## Format

```yaml
version: 1
name: accounts-payable guardrails
policy_set: payments-v2
delegations:
  principals:
    alice: { id: company-user-42, kind: human }
    ap:    { id: accounts-payable-agent, kind: agent }
  grants:
    - id: root            # alias
      grantor: alice
      grantee: alice
      capabilities: [pay:vendor]
      resource_scope: ["vendor:*"]
      max_amount: { amount: "10000", currency: USD }
      expires_in: 30d
    - id: ap
      parent: root
      grantor: alice
      grantee: ap
      capabilities: [pay:vendor]
      resource_scope: ["vendor:*"]
      max_amount: { amount: "1000", currency: USD }
cases:
  - name: injected 12500 payment exceeds delegated authority
    agent: ap
    principal: alice
    delegation: ap
    capability: pay:vendor
    tool: payments
    action: send_payment
    resource: vendor:128
    arguments: { amount: "12500.00", currency: USD, destination_account: acct-offshore-9931 }
    expect:
      outcome: DENY
      reason_code: PAYMENT_EXCEEDS_DELEGATED_AUTHORITY
      matched_policy: payments.vendor.max_amount.v1
```

All identifiers are pattern-checked, `arguments` are capped at 16 KiB, extra
fields are rejected, parents must be declared before children, and aliases
must resolve. See `packages/evals/src/atp_evals/regression/format.py`.

## Recording from a trace

`atp record` is a **deterministic conversion**, not generation. It takes the
envelope, the delegation-chain snapshot and the decision from a trace and
writes a case whose expectation is the decision the gateway actually made.
Review it: if the recorded decision was the *wrong* one (as in Demo B, where
`payments-v1` allowed a redirected payment), change `expect` to the decision
you want to keep, and run the suite under the policy set that produces it.

Traces are untrusted input. The recorder validates every field through the
strict suite models, drops provenance excerpts and content hashes, refuses
traces without a resolved chain, and refuses chains whose leaf is not the
envelope's agent. Nothing from a trace is ever executed.

No LLM is involved anywhere in this workflow.

## CI

`examples/regression-suite/.github/workflows/agent-security-tests.yml` runs
every `security/*.yaml` suite on push and PR, needs no secrets, and uploads
JUnit XML so failures show up as annotations. This repository's own CI runs
the sample suite and asserts that it fails under `payments-v1`.

## Limits

- Suites test the gateway's decision for a given graph and policy set. They
  do not test your agent's prompt, your tools, or whether an attacker can
  reach a tool without the gateway.
- Policy sets are Python code in `atp_policy.registry`; a suite can select a
  version but cannot define new policies.
- `expires_in` is relative to run time, so a suite cannot pin "expired
  delegation" cases yet.
