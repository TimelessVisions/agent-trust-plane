# Versioning and migrations

| Artifact | Version field | Current | Policy |
|---|---|---|---|
| Package `agent-trust-plane` | `pyproject.toml` | 0.3.0 | SemVer while 0.x: breaking changes in minor versions, called out in CHANGELOG "Changed" |
| Regression suite | `version:` | 1 | Loader accepts exactly the versions it knows (`ge=1, le=1`); an unknown version is an error, never a guess |
| Policy file | `version:` | 1 | Same rule |
| Proxy config | none (0.x) | — | Strict models (`extra=forbid`); unknown keys fail loudly; a `version` field will be added before 1.0 |
| Trace events | implicit (event types + payload shapes) | — | Additive only: new event types and payload keys may appear; existing keys are never reinterpreted |
| Decision | fields with defaults (`enforcement` added in 0.3.0) | — | Old stored decisions validate with defaults (`enforce`) |
| Execution grant token | `v: atp-grant/1` | 1 | A new format gets a new tag; old tokens are rejected, not reinterpreted |
| Evidence bundle | `bundle_version` | 1 | Verifier rejects unknown versions |
| HTTP API | path-versionless while 0.x | — | Additive changes only within a minor; removals/renames bump the minor and are listed |

## Migration rules

1. **Never silently reinterpret old authorization evidence.** A reader that
   does not understand a version must refuse, not guess. Every file format
   carries a version and the loaders pin it.
2. **Additive first.** New optional fields with defaults
   (`Decision.enforcement`) keep old records readable.
3. **Suites migrate by rewriting.** When suite version 2 exists, an
   `atp regression migrate` command (not yet written) will read v1 and write
   v2; running a v1 suite with a v2-only runner is an error with a pointer to
   the command.
4. **Stored SQLite schema.** Tables are created with `CREATE TABLE IF NOT
   EXISTS`; there is no migration framework yet. A schema change in 0.x
   ships with a script and a CHANGELOG entry; the safe path is to keep the
   old `.atp/` for evidence and start a new one.
5. **Replay across versions.** Replay uses the recorded authority snapshot
   and the named policy set; a set that no longer exists yields
   `POLICY_SET_NOT_FOUND`, not a fallback.

## Breaking changes in 0.3.0

- `ToolMapping.resource_arguments` removed (placeholders are derived from
  the template); resource arguments are no longer stripped from the
  forwarded/hashed arguments.
- Resource templates may not contain `*` (`note:*` → `note:_list`).
- `atp mcp-init` replaced by `atp mcp init -- <command>`; `atp mcp-proxy`
  kept as a hidden alias of `atp mcp proxy`.
- `atp_adapter_mcp.McpInterceptor` (in-process shim) removed.
- Resource grammar widened (`/` and most printable characters allowed in
  ids); scope patterns gained `type:prefix*`.
