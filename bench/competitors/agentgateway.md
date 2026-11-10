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

**Where this is documented, and the risk it carries.** Body access inside `mcpAuthorization`
is shown by the v1.6.0 *source*, `crates/agentgateway/src/mcp/streamablehttp.rs` lines
155–158, with the comment quoted above. The MCP authorization docs (`schema/cel.md`, the
`mcp-authorization` example) do not say that `request.body` is available there; they document
only `mcp.tool.*`. So this is source-level behaviour of v1.6.0 and may change in a later
release. The bench pins v1.6.0, and the binary tests below fail loudly if it stops holding.

**Parser agreement, checked on the binary.**

- *Duplicate keys.* For `"amount":50,"amount":500` the CEL `json()` sees 500 and denies; for
  `"amount":500,"amount":50` it sees 50 and allows, and the upstream also executed 50 (the
  journal holds `amount: 50`). Both parsers keep the last key, so a duplicate cannot show CEL
  one value and the tool another. A duplicate `arguments` key under `params` is rejected by
  the gateway (`-32603 invalid params for method: tools/call`) and never reaches the upstream.
- *JSON-RPC batches.* A batch (`[{...},{...}]`) is rejected before authorization with HTTP 400
  `mcp: fail to deserialize request body`; nothing reaches the upstream. So a batch cannot
  smuggle a second call past a per-call rule.

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
| `resource_scope` + `resource_args` (resource `dojo.<suite>:{arg}`) | Every branch starts with the id guard `has(a.<arg>) && a.<arg> != null && (type string \|\| int \|\| uint) && string(a.<arg>).matches("\\A[^*\\x00-\\x1f\\x7f]{1,255}\\z")`, ATP's `RESOURCE_PATTERN` id part (1–255 code points, no `*`, no control characters; ATP rejects such a resource before any matching). `*` and `dojo.<suite>:*` are the guard alone. Exact and prefix patterns add `&& (string(a.<arg>) in [exact ids] \|\| string(a.<arg>).startsWith("<prefix>") ...)`. Patterns of another type are skipped. If no pattern can match, the tool gets no rule. |
| `resource_scope` for a tool without a resource argument (`tool:<name>`) | Checked at render time with ATP's own `scope_matches`. If it is out of scope, the tool gets no rule, because ATP's kernel would deny every call to it. |
| `argument_max` / `argument_min` | `N.with(n, n - n == 0.0 && n <= M)` (`>= M` for min), where `N` is `double(a.x)` for a JSON number and, for a string, `double(a.x.trim().replace("_", ""))` after checking every `_` sits between two digits (else a deliberate parse error). `n - n == 0.0` is false for ±infinity and NaN, which ATP's `_to_decimal` rejects. Booleans and non-numbers are a CEL error, so the rule is false: deny, as in ATP. |
| `argument_allowed_values` | Typed membership (literals are written with `json.dumps(..., ensure_ascii=False)`, so non-BMP characters are literal, not surrogate escapes): `type(a.x) == string && a.x in [...]`, the same for `bool`, and `(int\|uint) && int(a.x) in [...]` for integers. As in ATP, `true` never matches `1` and `"5"` never matches `5`. agentgateway's `json()` yields `uint` for non-negative integers, so both are accepted. |
| `argument_subset_of` | `(type(a.x) == list ? a.x : [a.x]).all(i, <typed membership of i>)` |
| `argument_required` | `has(a.x) && a.x != null` for each argument |
| `argument_forbidden` | `!has(a.x)` for each argument. As in ATP, an explicit `null` counts as present. |
| `optional: true` | `!(present) \|\| <check>` |
| `argument_max_length` | String: `size(a.x) <= N \|\| a.x.matches("\\A(?s:.){0,N}\\z")`. CEL `size()` counts UTF-8 bytes while ATP counts code points; bytes ≤ N implies code points ≤ N, and agentgateway's regex (Rust `regex`) is Unicode-aware, so the regex counts code points exactly. For N > 10000 the regex does not compile in v1.6.0 (100000 fails on the binary), so only `size()` is used and strings are enforced on UTF-8 bytes (stricter for non-ASCII), recorded as a `DroppedConstraint`. List or object: `size(a.x) <= N`. Number or boolean: passes (dropped; see below). |
| `deny`, `require_approval` | The tool gets no rule. agentgateway has no approval flow, and ATP's REQUIRE_APPROVAL never lets the call reach the upstream either, so a denial is the faithful rendering. |

The bench tests `test_rendered_rules_match_atp_semantics_on_binary` (38 calls) and
`test_resource_ids_and_unicode_match_atp_on_binary` (12 calls) drive every rule kind through
the pinned binary when executed, including infinities, NaN, padded and underscored numeric strings, invalid
and 255/256-code-point resource ids under a prefix scope and under `dojo.banking:*`, code-point
string lengths and a non-BMP allowed value. They check every decision, and the journal,
against ATP's semantics. The new edge-case coverage requires a fresh pinned-binary run before D2 can be marked complete.

## What is dropped and why

`RenderedPolicy.dropped` lists each dropped element as a `DroppedConstraint` with its source
rule id, the reason and the doc URL. The runner writes them to `dropped.json` and prints the
count for each layer in `summary.md`.

- **`argument_max_length` on numbers or booleans.** ATP measures the length of the value's
  canonical JSON text. agentgateway's CEL functions
  (https://github.com/agentgateway/agentgateway/blob/v1.6.0/schema/cel-functions.md) cannot
  produce that text, so such values pass. Strings, lists and objects are enforced.
- **`argument_max_length` above 10000 on strings** is enforced on UTF-8 bytes (stricter for
  non-ASCII), as explained in the mapping table.
- **Nothing else.** None of the 1.0 annotations (banking, slack, travel, workspace) uses
  `argument_max_length`. Their rendered policies therefore drop **zero** constraints, which
  `test_argument_rules_listed_as_dropped` pins.

These are approximations rather than drops, and they are recorded here so that nobody reads
them as weakening:

- **Decimal limits.** Limits compare as IEEE doubles, while ATP compares them as Decimals.
  This can only matter at the 1e-15 relative scale, which includes integers above 2^53
  (9007199254740993 becomes 9007199254740992.0, so a value one above a limit that large
  could pass).
- **Numeric strings CEL reads differently from `Decimal`.** Matched: surrounding whitespace
  (`" 50 "`), digit-separating underscores (`"1_000"`; `"1__0"` and `"_1"` are rejected by
  both), signs, `".5"`, exponents, and `inf`/`Infinity`/`NaN` in any case (rejected by both).
  Not matched: a string whose `Decimal` value is finite but overflows a double (`"1e400"`
  becomes infinity and is denied; ATP allows it under an `argument_min`, denies it under an
  `argument_max`), and non-ASCII digits such as fullwidth `"５０"` (ATP's `Decimal` reads 50;
  CEL fails to parse and denies). Both differences are stricter than ATP, and no AgentDojo
  argument takes such values.
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
