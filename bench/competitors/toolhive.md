# ToolHive v0.55.2 (Cedar) — benchmark competitor profile

**Pinned upstream:** [stacklok/toolhive tag v0.55.2](https://github.com/stacklok/toolhive/tree/v0.55.2).  
**Layer:** `toolhive` — `bench/src/atp_bench/layers/toolhive_layer.py`.  
**Status:** Candidate implementation. Binary-backed outcomes require a tested Docker/Podman-capable execution environment; `ENV_BLOCKED` is not a denial, a pass, or a measured benchmark result.  
**Ground truth:** The identical, pre-injection task annotation is used to render ATP and ToolHive. The annotation YAMLs are owner-controlled and unchanged. This layer does **not** execute injected agent code and does not use paid model APIs.

## Evidence and pinned references

| Capability / limitation | Versioned reference |
|---|---|
| Authorization middleware; `cedarv1`; remote workloads | [Authorization framework](https://github.com/stacklok/toolhive/blob/v0.55.2/docs/authz.md) |
| `arg_<name>` scalar values in policies | [Cedar argument preprocessing](https://github.com/stacklok/toolhive/blob/v0.55.2/pkg/authz/authorizers/cedar/core.go) |
| Conversion of JSON floating-point values to Cedar decimals | [Cedar value conversion](https://github.com/stacklok/toolhive/blob/v0.55.2/pkg/authz/authorizers/cedar/entity.go) |
| Remote URLs, `--authz-config`, `--foreground`, `--proxy-port` | [Pinned `thv run` reference](https://github.com/stacklok/toolhive/blob/v0.55.2/docs/cli/thv_run.md) |
| Authorization denial: HTTP 403 with JSON-RPC code 403, message `Unauthorized` | [Authorization middleware](https://github.com/stacklok/toolhive/blob/v0.55.2/pkg/authz/middleware.go), [error-code definition](https://github.com/stacklok/toolhive/blob/v0.55.2/pkg/mcp/errors.go) |

The actual pinned ToolHive source (not just the high-level documentation) distinguishes:
- A **string, boolean, integer, or JSON number** is exposed to Cedar as `arg_<name>`.
- A **list, object, or null** is represented only by `arg_<name>_present = true`, with no inspectable item values.
- The entity converter maps JSON numbers to Cedar **decimal** values; comparisons therefore use `decimal("N.0")` and decimal comparison methods, not integer `<=` against an unconverted number.

## Per-task enforcement mapping

| ATP annotation element | Cedar representation |
|---|---|
| `capabilities` | One `permit` per allowed `Tool::"<tool>"`, with `Action::"call_tool"`. Unlisted tools have no permit, so Cedar denies them by default. |
| `resource_scope` without `resource_args` | ATP's exact `tool:<name>` scope check at render time. Tools outside scope receive no permit. |
| `resource_scope` with a mapped resource argument | Every matching scope is expressed using `resource.arg_<name>`. Exact values use equality, prefixes use Cedar `like "<prefix>*"`. Numerical exact IDs have string and decimal alternatives. |
| `argument_max`, `argument_min` | Decimal comparison methods `lessThanOrEqual` and `greaterThanOrEqual` on scalar values with `decimal("...")`. The pinned Go parser represents JSON numbers as float64 prior to Cedar conversion. |
| `argument_allowed_values` | Typed equality for strings, booleans and integer-valued JSON numbers (mapped to Cedar decimal); multiple allowed values are OR-ed. |
| `argument_required` | Presence of `arg_<name>` OR `arg_<name>_present`, except that null and a complex value cannot be told apart. |
| `argument_forbidden` | Absence of both `arg_<name>` and `arg_<name>_present`. |
| `argument_subset_of` | **Dropped** for lists: ToolHive only exposes the presence of a list, not its items. |
| `argument_max_length` | **Dropped** for general values, especially lists and objects, whose contents aren't exposed. |
| `optional: true` | A missing or explicit-null scalar `arg_<name>` passes. A complex value is indistinguishable from null and is approximated as absent. |
| `deny`, `require_approval` | No `permit` is generated for the rule's tool. ATP never forwards `REQUIRE_APPROVAL` without approval, and ToolHive has no equivalent human-approval flow in this reference configuration. |

The renderer returns `RenderedPolicy(files={"cedar.json": ...}, dropped=[...])`. Each dropped rule records its annotation rule ID, reason, and a pinned ToolHive source URL. It does not silently omit list subset, length, or non-renderable arguments.

## Residual mismatches (not claims of equivalence)

These differences must be accounted for in any results page or peer review.

1. **Resource ID grammar:** ATP rejects empty IDs, controls, `*`, and IDs longer than 255 Unicode code points. Cedar `like` on a scalar cannot fully reproduce this grammar through ToolHive's exposed policy surface. Exact IDs are stricter than the grammar; prefix or wildcard rules can be weaker. The benchmark does not pretend the resulting authorization outcome is identical.
2. **Numeric strings:** ATP parses finite numeric strings with Python `Decimal`; ToolHive's scalar string is not automatically a Cedar decimal. Numeric string arguments can be denied more strictly than ATP.
3. **Number precision:** ToolHive's Go JSON decoding and Cedar decimal conversion can round numbers, while ATP checks `Decimal(str(value))`. Boundary comparisons at large values or fine fractional precision may differ.
4. **Complex versus null arguments:** `arg_<name>_present` is emitted for both. For `argument_required`, null may be erroneously admitted; for optional scalar constraints a complex argument may bypass the constraint. This is a ToolHive presentation limitation, not evidence that ATP's annotation was wrong.
5. **UTF-8 and Unicode:** Literal encoding and Cedar string matching need real-binary checks for non-ASCII. We do not extrapolate from the Python renderer.
6. **Tool/list visibility:** ToolHive's `tools/list` response filtering and remote proxy startup may affect visible tools. The upstream journal, rather than an HTTP response alone, remains the source of truth for reached calls.
7. **Runtime:** ToolHive's pinned binary may require Docker/Podman for a remote workload. If `thv run` cannot start due to the runtime, `ToolhiveLayer.open()` raises `EnvBlocked` with stderr. A malformed Cedar policy or an unexpected deny response is **FAIL/INCONCLUSIVE**, not silently reclassified as ENV_BLOCKED.

## How to verify (Linux x86-64)

The pin is recorded in `bench/data/tool_pins.yaml` (ToolHive v0.55.2 asset SHA256 `4336f1fafe173140e8d6a9f0537c32aff35059b4563b664905751fda6f612f44`). It is SHA256-checked by `fetch_tool` before execution.

```bash
cd bench
uv sync --frozen
uv run --no-sync pytest -q -p no:cacheprovider \
  tests/test_toolhive_layer.py --junitxml=/tmp/d3.xml

# Check Docker/Podman availability separately:
docker info
```

**D3 evidence required:** exact JUnit counts; SHA256-pinned `thv` path/version; rendered Cedar policy and parsed config; a denied request and journal absence; an allowed request and journal presence; clear `ENV_BLOCKED` if there is no container runtime; full root, bench, lint/type gates; and independent review of all approximations. A local tool checkout or an apparent green workflow **alone** does not prove binary-backed authorization behavior.

**No competitive scores yet:** A1 pre-registration and the owner-gated `bench-annotations-v1` tag must occur before D5 full sweeps. No numerical comparison against other products should be published before that owner gate.
