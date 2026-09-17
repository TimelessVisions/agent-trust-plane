# MCP proxy — `atp mcp wrap`, `atp mcp proxy`, scope, and what it does not protect

The proxy is a stdio MCP server that fronts **one** upstream MCP server
(stdio child process or Streamable HTTP endpoint). Every `tools/call`
becomes an `ActionEnvelope`, is decided by the gateway, released under a
single-use grant, forwarded, and its outcome reported back against that
grant. Unmapped tools are denied and hidden from `tools/list` by default.

```
MCP client (Claude Desktop, Cursor, your agent)
   │ stdio (JSON-RPC)
   ▼
atp mcp wrap ─┬─ in-process gateway from .atp/  (authorize → execute/release → outcome)
              │
              └─ stdio child  or  Streamable HTTP ──▶ upstream MCP server (only after release)
```

Two ways to run it:

| | `atp mcp wrap` (local-first) | `atp mcp proxy` (remote gateway) |
|---|---|---|
| Gateway | in the same process, persistent store in `.atp/` | `atp serve` elsewhere, reached over HTTP |
| Keys / credentials | generated once into `.atp/keys.env`; a session credential and delegation are issued per run from `authority:` | operator issues a credential; `$ATP_AGENT_TOKEN`; `delegation_grant_id` in the config |
| Offline commands (`trace`, `regression add`, `explain`, `mutate`, `evidence`) | read `.atp/` directly | `atp record --gateway URL --operator-key …` |
| Mode | `--mode enforce` (default) or `--mode shadow` | `ATP_ENFORCEMENT_MODE` on the gateway |
| Use for | development, CI, single-machine agents | a shared gateway with its own boundary |

## Quick path

```bash
atp mcp init --name fs -- npx -y @modelcontextprotocol/server-filesystem /abs/sandbox
#   discovers tools/list, proposes capabilities from annotations, writes atp-mcp.yaml
#   and .atp/policies.yaml (declared set fs-v1); review both.
atp mcp wrap --config atp-mcp.yaml                 # or --mode shadow to observe first
```

Point the MCP client at the wrap command (see [frameworks.md](frameworks.md)).
Then `atp trace list`, `atp policy explain TRACE`, `atp regression add TRACE`,
`atp test atp-regression.yaml`.

## Verified against

| Upstream | Transport | How | Where |
|---|---|---|---|
| `notes_mcp_server` (this repo; annotated tools) | stdio | `uv run atp demo wrap`, `atp demo mcp`, wrap e2e, proxy e2e | every CI run |
| `notes_mcp_server` served by uvicorn | Streamable HTTP | `adapters/mcp/tests/test_proxy_http_upstream.py` | every CI run |
| `@modelcontextprotocol/server-filesystem` (Node) | stdio | `ATP_E2E_NPX=1 uv run pytest adapters/mcp/tests/test_proxy_third_party.py` | opt-in; passed 2026-09-17 on Windows 11 / Node 24 |

Full matrix incl. what was *not* verified: [compatibility.md](compatibility.md).

## Supported

- **Protocol**: MCP as implemented by the official Python SDK 2.2.x
  (`mcp>=2.2,<3`); the proxy is a lowlevel `Server`, the upstream is driven
  with `ClientSession`. Version negotiation is the SDK's.
- **Transports**: served over stdio; upstream over stdio (`upstream.command`)
  or Streamable HTTP (`upstream.url`, `https://` or localhost `http://`,
  static `headers` and secret `headers_env`).
- **Methods**: `tools/list` (filtered) and `tools/call`. Prompts, resources,
  sampling, elicitation, tasks, notifications and `input_required` results
  are **not** proxied (`UPSTREAM_UNSUPPORTED_RESULT`).
- **Modes**: enforce; shadow (denials forwarded, recorded as `WOULD_DENY`).

## Config reference (`atp-mcp.yaml`)

```yaml
server_name: fs                     # envelopes use tool "mcp.fs"
principal: {id: local-user, kind: human}     # default
agent: {id: fs-agent, kind: agent}           # default "<server_name>-agent"
policy_set: fs-v1                   # declared in .atp/policies.yaml (wrap) or built-in
upstream:
  command: npx                      # stdio …
  args: [-y, "@modelcontextprotocol/server-filesystem", /abs/sandbox]
  env: {}                           # extra environment for the child (secrets live here, not on the agent host)
  # url: https://host/mcp           # … or Streamable HTTP
  # headers_env: {Authorization: UPSTREAM_TOKEN}
authority:                          # wrap only: what the human delegates to the session agent
  capabilities: [fs:read, fs:write] # fs:destroy is proposed but NOT delegated
  resource_scope: ["path:/abs/sandbox/*"]
  expires_in: 12h
tools:
  - mcp_tool: write_file
    tool: mcp.fs
    action: write_file
    capability: fs:write
    resource_template: "path:{path}"
    path_normalization: {casefold: false}   # base_dir for relative paths; casefold on case-insensitive FS
  - mcp_tool: move_file
    tool: mcp.fs
    action: move_file
    capability: fs:destroy
    resource_template: "path:{source}"
expose_unmapped_tools: false
request_timeout_seconds: 30
gateway: http://127.0.0.1:8000       # proxy mode only
delegation_grant_id: grt_…           # proxy mode only
agent_token_env: ATP_AGENT_TOKEN     # proxy mode only
```

`atp mcp init` writes this from `tools/list`: read-only tools →
`<server>:read`, destructive → `<server>:destroy`, others → `<server>:write`;
path-like arguments (`path`, `file_path`, `directory`, …) → `path:{arg}`
with normalisation; id-like arguments → `<arg>:{arg}`; otherwise
`tool:<name>`. Annotations are unverified server claims; the file is a
proposal you review (`../security/safe-defaults.md`).

## Policies that apply

Kernel: delegation valid, capability held, resource in scope (prefix
scopes such as `path:/abs/sandbox/*` after normalisation). Declared rules
from the policy set: argument limits, allowed values, deny, approval
([../policies/policies.md](../policies/policies.md)). Payment policies
apply only to `tool: payments`.

## What this protects and what it does not

Protects: every call that goes *through the proxy* — decided against
delegated authority, bound to a single-use grant over the exact
arguments, recorded with what came back.

Does not protect: an agent that launches or reaches the upstream itself
(`test_direct_upstream_access_is_not_protected`, on purpose). Whether that
can happen is a deployment property:
[../security/enforcing-the-boundary.md](../security/enforcing-the-boundary.md).
Also not covered: symlinks inside a scoped directory; a wrong `casefold`
setting on a case-insensitive filesystem; a lost outcome report
([../security/idempotency.md](../security/idempotency.md)).

## Trace shape for a proxied call

Allowed: `action_proposed` → `delegation_resolved` → `policy_evaluated` →
`decision_made` → `grant_issued` → `execution_attempted` →
`execution_released` → `execution_completed` (actor: the agent,
`reported_by: external_executor`, bounded summary).
Denied (enforce): … → `decision_made` (DENY); nothing after.
Denied (shadow): … → `decision_made` → `shadow_would_deny` →
`shadow_execution_completed|failed`.
The envelope's provenance records the upstream transport and negotiated
protocol version.
