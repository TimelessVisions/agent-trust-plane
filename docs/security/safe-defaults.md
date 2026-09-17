# Safe defaults and failure behaviour

Every default was reviewed with one question: if this input is missing,
wrong or hostile, does a side effect become possible? The answer must be
"no" for anything consequential, and the failure must be visible.

| Situation | Behaviour | Where |
|---|---|---|
| Unknown / unmapped MCP tool | Denied under capability `mcp:unmapped`, hidden from `tools/list` (`expose_unmapped_tools: false`) | proxy |
| Mapped tool whose capability is not delegated | `DENY CAPABILITY_NOT_GRANTED`; init never delegates `<server>:destroy` | kernel, init |
| Tool argument needed for the resource is missing / non-scalar / produces an invalid resource | `TOOL_ARGUMENTS_INVALID`, nothing sent to the gateway or upstream | mapping |
| Relative path with no `base_dir` | refused | `PathNormalization` |
| Arguments over 15 KiB (proxy) / 16 KiB (envelope) | refused, never truncated | proxy, envelope |
| Policy set name unknown | `POLICY_SET_NOT_FOUND`; the gateway does not start with an unknown default | registry, wiring |
| Policy file unreadable / malformed / > 1 MiB / shadows a built-in | load fails; the command exits 2; `atp mcp wrap` refuses to start | declarative |
| Missing `authority` section in `atp-mcp.yaml` | `atp mcp wrap` refuses (nothing to delegate) | wrap |
| Missing execution grant | `GRANT_MISSING`, blocked | kernel |
| Grant for a different action / agent / expired / used | blocked with the specific reason; store unchanged | kernel |
| Credential revoked between HTTP auth and the locked path | re-checked under the lock; refused | kernel |
| Delegation revoked between authorize and execute | re-checked at execute; blocked | kernel |
| Shadow mode requested by a caller | impossible: no such parameter; `enforcement` is not an envelope field (`extra=forbid`) | API |
| Persistent gateway without keys | refuses to start (`InsecureConfigurationError`) | settings |
| `.env` present while using `atp mcp wrap` | ignored; the home's `keys.env` is authoritative | home |
| Upstream MCP server down / crashes | proxy fails to start (init/wrap) or the call returns `UPSTREAM_ERROR` and `execution_failed` is recorded | proxy |
| Upstream returns `input_required` / task results | `UPSTREAM_UNSUPPORTED_RESULT`; nothing further | proxy |
| Database locked / unavailable | request fails; no grant is minted without a stored record; no ledger row without a consumed grant | stores |
| Policy raises an exception | not caught: the request fails with 500 and no grant is minted (fail closed); the exception is a bug to fix, not a decision | engine |
| Recorded trace fed to `regression add` / `mutate` | strict models, size caps, no execution | recorder |
| Evidence bundle edited | `atp evidence verify` fails | evidence |

## Where fail-closed would cause harm, and what was done instead

- **Data loss on write tools.** ATP never partially executes: a call is
  either released whole or not at all. There is no "execute the safe half".
- **Availability.** A gateway outage stops all mediated tool calls. That is
  the intended trade for a boundary; put the gateway on the same host as
  the proxy (`atp mcp wrap` does) if that is unacceptable.
- **Shadow mode** exists precisely so teams can observe without blocking
  while they build policy; it is explicit in every trace and in `atp trace
  list` (`WOULD_DENY`).

## Defaults that are permissive on purpose, and why

- `atp mcp init` proposes delegating `<server>:read` and `<server>:write`
  so the first run produces an ALLOW as well as a DENY. The generated file
  says so and is meant to be narrowed; the destructive capability is never
  delegated by default.
- `expires_in: 12h` for a wrap session credential/delegation: long enough
  for a working day, short enough that a stolen session token dies.
- Generated path scope is `path:*` when the upstream command names no
  directory, with a note asking for a narrower prefix.
