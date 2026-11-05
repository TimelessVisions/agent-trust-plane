# Scoped MCP payment authority — 1.0 release candidate

**Status:** candidate implementation and failing incident retained for owner review. This project is not independently audited and has no production users. Do not interpret these instructions as approval to use real payment credentials or move funds.

## Threat boundary

The upstream MCP tool is not the native gateway-executed `payments` tool. `ProxyConfig` **rejects** mapping untrusted MCP tools onto the native name because doing so could execute a payment inside the gateway and then execute the tool again upstream. That prohibition must remain.

A legitimate mapped MCP payment explicitly declares `capability: pay:vendor`, uses a namespaced `mcp.*` envelope tool, and delegates only the approved vendor scope. The built-in `payments-v2` checks now apply to such actions, including aliases: valid amount/currency, a delegated single-payment maximum, an approved destination account from the trusted directory, and any approval threshold. Malformed payment arguments fail closed.

## Operator-reviewed local wrapper configuration

```yaml
version: 1
server_name: vendor-payments
upstream:
  command: /path/to/your-synthetic-mcp-server
authority:
  capabilities: [pay:vendor]
  resource_scope: ["vendor:128"]
  max_amount: {amount: "1000.00", currency: USD}
  currencies: [USD]
  expires_in: 1h
tools:
  - mcp_tool: send_payment
    tool: mcp.vendor-payments
    action: send_payment
    capability: pay:vendor
    resource_template: "vendor:128" # example is restricted to one vendor
    schema_sha256: "<reviewed initial MCP tool-definition SHA256>"
```

`atp mcp wrap` carries `max_amount` and `currencies` into both the human root and the session agent's grant, preserving the chain's limits. Cumulative `budget`, if configured, remains on the leaf to avoid double counting. **An omitted maximum is not unlimited permission:** `PaymentMaxAmountPolicy` denies a payment when no limit exists in the resolved delegation chain. A configured currency list must contain the limit currency.

### What is verified and what is not

- The policy-unit regressions check legitimate payments, unapproved accounts, limit overruns, approval thresholds, malformed arguments, and unrelated MCP actions.
- The local-wrapper tests inspect the grant payload and reject inconsistent currencies.
- The existing `under-limit-redirect` incident was written *before* the wrapper could express `max_amount`; **it remains unchanged and must be reported FAIL/INCONCLUSIVE as measured**, rather than silently edited to pass. Resolving its fixture/configuration compatibility is an **owner decision** under the E2 gate.
- Preventing an agent from bypassing the proxy and contacting its upstream directly requires deployment-level network and credential boundaries. Tool-definition pins do not guarantee that upstream implementation behavior is unchanged.
- A tool granted `pay:vendor` but not actually performing a financial action is now subject to the restrictive payment schema. Operators must not delegate payment authority to unrelated tools.
- This change is not an audited financial-control system, payment processor, or regulatory certification. Do not use real funds to test it.

## Evidence needed before a paid design-partner evaluation

The complete branch-specific tests, actual synthetic MCP allow/deny journal, mcp payment authorization regression, compatibility goldens, and clean reproducible setup must pass. Owner review and release gates are still required. A controlled **staging/synthetic** evaluation may be discussed before production claims, but never presented as a deployed security guarantee.

The long-term commercialization objective is a reusable policy and evidence layer for consequential agent actions. The short-term offer should be a scoped engineering evaluation, not production payment protection.
