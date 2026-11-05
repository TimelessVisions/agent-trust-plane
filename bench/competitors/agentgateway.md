# agentgateway in the replay benchmark

The `agentgateway` layer runs the AgentDojo suite server behind the real agentgateway
binary. For each task, its policy is generated from the same annotation that ATP receives.
The policy is the strongest one agentgateway v1.6.0 can express. Fairness rules: spec
"Anti-goals" and "Competitors get the same per-task information"; ruling R13.

## Version

- agentgateway **v1.6.0** (`agentgateway -V` prints `1.6.0`). The release asset is
  `agentgateway-linux-amd64`. It is pinned by SHA-256 in `bench/data/tool_pins.yaml`, and
  `atp_bench.tools.fetch_tool` fetches it into `bench/.tools/agentgateway/v1.6.0/`.
- Source read at tag `v1.6.0`, commit `ea56086`.
- Only a Linux build is pinned. On Windows, and on any platform without a pinned build, the
  layer raises `EnvBlocked`. The runner then reports every item as ENV_BLOCKED, which is never
  counted as a decision.

## Doc URLs relied on

The agentgateway.dev site could not be reached from the build container, so every citation
points at the documentation and source in the repository at the tag:

| What | URL |
|---|---|
| CEL variables: `request.body`, `mcp.methodName`, `mcp.tool.name`, `mcp.tool.arguments` | https://github.com/agentgateway/agentgateway/blob/v1.6.0/schema/cel.md |
| CEL functions: `json()`, `with()` | https://github.com/agentgateway/agentgateway/blob/v1.6.0/schema/cel-functions.md |
| Config schema: `mcp`, `targets`, `policies.mcpAuthorization`, `config.*Addr` | https://github.com/agentgateway/agentgateway/blob/v1.6.0/schema/config.md |
| `mcpAuthorization` example | https://github.com/agentgateway/agentgateway/blob/v1.6.0/examples/mcp-authorization/README.md |
| How authorization builds its CEL context (name and target only) | https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/mcp/rbac.rs |
| The raw request body kept in the authorization CEL context | https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/mcp/streamablehttp.rs |
| Deny response shape (`authorization_denied_returns_unknown_tool_error`) | https://github.com/agentgateway/agentgateway/blob/v1.6.0/crates/agentgateway/src/mcp/mcp_tests.rs |
| Issue #2069, "Support tool arg MCP auth" (open) | https://github.com/agentgateway/agentgateway/issues/2069 |

## The finding that changes the plan: arguments are visible

The plan assumed agentgateway cannot authorize on tool arguments, and so would drop every
argument and scope constraint. **That assumption is wrong for v1.6.0.**

- The documented `mcp.tool.arguments` variable is **empty** at authorization time.
  `McpAuthorizationSet::validate` builds `MCPInfo` from the resource name and target only
  (`rbac.rs`). Issue #2069 says the same: "our MCP auth runs on the tool name only". A rule
  `mcp.tool.name == "send_money" && mcp.tool.arguments.amount < 100.0` denied every call,
  including an amount of 50, on the binary.
- However, the Streamable HTTP handler keeps the **original HTTP request bytes** in the CEL
  context that `mcpAuthorization` evaluates (`streamablehttp.rs`: "Keep the original HTTP
  bytes for detached authorization and guardrail CEL"). `request.body` and `json()` are
  documented CEL. So `json(request.body).params.arguments` is the call's arguments. On the
  binary, `... && json(request.body).params.arguments.amount < 100.0` allowed 50 and
  denied 500 before the upstream; the journal holds only the allowed call.

So the layer **enforces argument rules and the resource scope** from the body. Leaving them
out would have made agentgateway weaker than its own product allows, which is the first
anti-goal. Ruling: *agentgateway policies read arguments via
`json(request.body).params.arguments`. Reason: v1.6.0 exposes the raw body to
`mcpAuthorization` CEL, which was verified on the binary. Cost if wrong: none for fairness,
since this direction only makes the competitor stronger.*

Limit: this works on HTTP transports, where a body exists. The bench always runs
agentgateway in front of the HTTP suite server.

## Generated config

`render_agentgateway_config(suite, annotation, upstream_url, port)` returns a
`RenderedPolicy` with `config.yaml` and the list of dropped constraints:

```yaml
config: {enableIpv6: false, adminAddr: 127.0.0.1:<p>, statsAddr: ..., readinessAddr: ...}
mcp:
  port: <port>
  policies:
    mcpAuthorization:
      rules:
      - mcp.tool.name == "read_file" && (mcp.methodName != "tools/call" || json(request.body).params.with(p, has(p.arguments) ? p.arguments : {}).with(a, <conditions>))
      - ...
  targets:
  - {name: dojo, mcp: {host: http://127.0.0.1:<upstream>/mcp}}
```

How the policy is shaped:

- **Allow rules.** There is one allow rule per granted tool, and allow rules are OR-ed.
  `tools/list` is filtered by name only, because a list request carries no arguments.
- **Fail closed.** A CEL evaluation error (a missing key, or `double("lots")`) makes the rule
  false, so the call is denied.
- **No granted tool.** The rule list becomes `["false"]`, because an empty list means "no
  policy" in agentgateway.
- **IPv6 and listeners.** `enableIpv6: false` and loopback admin, stats and readiness
  addresses are set only so that the binary starts in containers without IPv6. Without them,
  it fails with "readiness server starts: Address family not supported". They do not change
  any decision.

## Mapping of each annotation element

Every element is rendered against the semantics of `atp_policy.declarative.DeclaredRule` and
`atp_identity.scope.matches`. In the table, `a` is the call's arguments.

| Annotation element | agentgateway CEL |
|---|---|
| `capabilities` (tool names) | One rule per tool: `mcp.tool.name == "<tool>"`. Tools not listed get no rule, so they are denied. |
| `resource_scope` + `resource_args` (resource `dojo.<suite>:{arg}`) | `has(a.<arg>) && a.<arg> != null && (string or int) && !string(a.<arg>).contains("*") && (string(a.<arg>) in [exact ids] \|\| string(a.<arg>).startsWith(<prefix>) ...)`. `*` or `dojo.<suite>:*` only needs the argument present. If no pattern can match, the tool gets no rule. |
| `resource_scope` for a tool without a resource argument (`tool:<name>`) | Checked at render time with ATP's own `scope_matches`. If it is out of scope, the tool gets no rule, because ATP's kernel would deny every call to it. |
| `argument_max` / `argument_min` | `double(a.x) <= M` / `>= M`. Like ATP, numeric strings are accepted, while booleans and non-numbers fail. |
| `argument_allowed_values` | Typed membership: `type(a.x) == string && a.x in [...]`, the same for `bool`, and `(int\|uint) && int(a.x) in [...]` for integers. As in ATP, `true` never matches `1` and `"5"` never matches `5`. agentgateway's `json()` yields `uint` for non-negative integers, so both are accepted. |
| `argument_subset_of` | `(type(a.x) == list ? a.x : [a.x]).all(i, <typed membership of i>)` |
| `argument_required` | `has(a.x) && a.x != null` for each argument |
| `argument_forbidden` | `!has(a.x)` for each argument. As in ATP, an explicit `null` counts as present. |
| `optional: true` | `!(present) \|\| <check>` |
| `argument_max_length` | `size(a.x) <= N` for strings, lists and objects. Partly dropped; see below. |
| `deny`, `require_approval` | The tool gets no rule. agentgateway has no approval flow, and ATP's REQUIRE_APPROVAL never lets the call reach the upstream either, so a denial is the faithful rendering. |

The bench test `test_rendered_rules_match_atp_semantics_on_binary` drives 23 calls, covering
each rule kind, through the real binary. It checks every decision, and the journal, against
ATP's semantics.

## What is dropped and why

`RenderedPolicy.dropped` lists each dropped element as a `DroppedConstraint` with its source
rule id, the reason and the doc URL. The runner writes them to `dropped.json` and prints the
count for each layer in `summary.md`.

- **`argument_max_length` on numbers or booleans.** ATP measures the length of the value's
  canonical JSON text. agentgateway's CEL functions
  (https://github.com/agentgateway/agentgateway/blob/v1.6.0/schema/cel-functions.md) cannot
  produce that text, so such values pass. Strings, lists and objects are enforced.
- **Nothing else.** None of the 1.0 annotations (banking, slack, travel, workspace) uses
  `argument_max_length`. Their rendered policies therefore drop **zero** constraints, which
  `test_argument_rules_listed_as_dropped` pins.

These are approximations rather than drops, and they are recorded here so that nobody reads
them as weakening:

- **Decimal limits.** Limits compare as IEEE doubles, while ATP compares them as Decimals.
  This can only matter at the 1e-15 relative scale.
- **Delegation chain.** ATP's kernel delegation checks (signature, expiry, revocation) have
  no counterpart here. They are not part of the per-task annotation, and agentgateway
  authenticates callers by JWT instead.

## How agentgateway's decisions are classified

On the binary, a denied `tools/call` returns HTTP 400 with:

```json
{"jsonrpc":"2.0","id":2,"error":{"code":-32602,"message":"Unknown tool: update_password"}}
```

This is the same shape as for a tool that does not exist (see the `mcp_tests.rs` link above).
Every call the bench makes names a tool that the upstream serves, so `classify_error` maps
exactly code `-32602` with message `Unknown tool: <the called tool>` to **DENIED**. Any other
JSON-RPC error, a timeout or a transport failure is **INCONCLUSIVE**. A result that came back,
including an upstream tool error (`isError`), is **ALLOWED**, as in the ATP layer. As always,
"reached upstream" is decided only by the suite server's journal.

## How to reproduce

On Linux amd64, from `bench/`:

```bash
uv run pytest tests/test_agentgateway_layer.py -q        # render, drops, real binary e2e
uv run python -m atp_bench run --layer agentgateway --layer atp --suite banking \
    --slice 2 --injections-per-task 2 --out /tmp/agw   # add --no-require-preregistration before the tag exists
cat /tmp/agw/summary.md /tmp/agw/dropped.json
```

The first run downloads the pinned binary and verifies its SHA-256. If the download, the
hash or the platform fails, the layer is ENV_BLOCKED with the reason; it is never estimated.
Each item's work directory keeps `agentgateway.yaml` (the exact config used),
`agentgateway.log` and `suite_server.log`.
