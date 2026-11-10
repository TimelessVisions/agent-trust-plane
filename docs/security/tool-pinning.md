# MCP tool-definition pinning (v1 candidate)

**Scope:** The ATP MCP proxy in `release/v1/B12-atp-1.0`. Experimental release
candidate, no third-party security audit. Do not treat this as protection for
clients that connect directly to an upstream server.

## Threat: changed approved tool definitions

An agent can be shown an innocuous MCP tool description and schema when its
operator creates an authorization mapping. A compromised upstream may later
alter the same tool's description or input schema, including adding hostile
instructions. A gateway that authorizes solely by tool name could then
forward calls under permissions approved for a different tool definition.
This is the class of problem addressed by MCPoison-style attacks.

**Pinning is a second check, not a replacement for delegation.** ATP continues
to enforce capabilities, resources, argument rules and approvals on
recognized tool calls. A matching pin does not make an untrusted tool safe.

## Approved definition digest

`atp mcp init` proposes a `schema_sha256` field for every tool mapping.
The digest is lowercase SHA-256 of ATP's canonical UTF-8 JSON object:

```json
{
  "name": "write_note",
  "description": "Writes a note",
  "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}}
}
```

The canonicalizer recursively sorts object keys and removes insignificant
whitespace. A description or schema edit changes the digest. An object's
original key insertion order does not. The exact `description` value is
used, including `null` if absent. `annotations` and `outputSchema`
are intentionally **not** in the pin; changed annotations are not
covered, and a tool name/description/schema pin does not prove that a
server's actual behavior is unchanged.

```yaml
tools:
  - mcp_tool: write_note
    tool: mcp.notes
    action: write_note
    capability: notes:write
    resource_template: "note:{id}"
    schema_sha256: "<64 lowercase hex digits from approved tools/list>"
```

## Enforcement flow

1. At upstream session start, the proxy fetches `tools/list` and stores the
   current tool definitions. When the client asks for `tools/list`, any
   pinned mismatch is **excluded**, even if `expose_unmapped_tools` is true.
2. The SDK's `notifications/tools/list_changed` callback marks the
   upstream cache dirty. The next list/call refreshes it from the upstream.
   The notification handler itself does no blocking I/O.
3. **Every pinned `tools/call` re-fetches `tools/list` immediately
   before authorization**. This catches changes even if the untrusted
   upstream never sent a notification.
4. An absent or changed pinned definition is refused with the structured
   `TOOL_DEFINITION_CHANGED` reason code. Authorization, grant release
   and upstream tool invocation are never reached for this call.
5. If the upstream list cannot be refreshed, the proxy fails closed with
   `UPSTREAM_ERROR`; this is an unverified condition, not evidence that a
   definition was changed.
6. If no `schema_sha256` is configured, the mapping retains the legacy
   behavior. Backward compatibility is intentional, but **unpinned is
   weaker**. New configurations should be reviewed and pinned.

## Migration / review

Regenerate a **draft** with `atp mcp init` and review the proposed
`schema_sha256` values against the server you actually intend to trust.
Preserve any existing manually scoped capabilities, paths, policies and
approval rules. Do not blindly overwrite an established configuration.
An operator who intentionally approves a changed schema can update the
pin after reviewing its new definition; this is a human trust decision.

## Security boundaries and limitations

- The proxy can be bypassed by directly reaching the upstream server; keep
  that path unreachable from agents that must be policy-restricted.
- The hash protects only the definition representation. It does not prove
  what server code executes, prevent intentional malicious descriptions
  approved at first registration, or prevent a tool's *runtime behavior*
  from changing without a schema change.
- Re-listing before each pinned call narrows but cannot eliminate all
  races between the list response and the subsequent upstream invocation.
  Network isolation and pinned upstream execution artifacts strengthen
  this boundary.
- Notification handling is lazy: the proxy refreshes when a client next
  lists or calls tools, rather than revalidating inside the callback.
  An already cached client-side tool list may remain visible, but the
  pinned call still fails closed.
- Existing `schema_sha256: null` or absent pins are accepted for
  compatibility and do **not** receive this protection.
- This is not evidence of prevention of any real-world attack until
  the incident tests and the external execution boundary are verified.

## Test evidence

`adapters/mcp/tests/test_tool_pinning.py` covers canonical digests,
`atp mcp init` proposal generation, changed definition removal and
denial, unannounced changes, transport errors on revalidation, and
legacy unpinned compatibility. CI results belong to the exact
release-branch commit and are never inferred from a green test in a
different commit.

No annotation YAMLs or public release artifacts are modified by this
feature. The A1 and H3 owner gates remain in force.
