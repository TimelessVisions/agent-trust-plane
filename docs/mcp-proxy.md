# MCP proxy — scope, setup, and what it does not protect

`atp mcp-proxy` is a stdio MCP server that fronts **one** upstream stdio MCP
server. Every `tools/call` is turned into an `ActionEnvelope`, authorized by
the gateway, released under a single-use grant, forwarded to the upstream,
and its outcome reported back against that grant. Unmapped tools are denied
and hidden from `tools/list` by default.

```
MCP client (Claude Desktop, Cursor, your agent)
   │ stdio (JSON-RPC)
   ▼
atp mcp-proxy ── HTTP ──▶ gateway: /authorize → /execute (release) → /executions/{grant}/outcome
   │ stdio
   ▼
upstream MCP server (only reached after a release)
```

## Verified against

| Upstream | How | Where |
|---|---|---|
| `notes_mcp_server` (this repo; MCP Python SDK 2.2 `MCPServer`) | `uv run atp demo mcp`, `adapters/mcp/tests/test_proxy_e2e.py` | every CI run |
| `@modelcontextprotocol/server-filesystem` (reference server, Node) | `ATP_E2E_NPX=1 uv run pytest adapters/mcp/tests/test_proxy_third_party.py` | opt-in; run 2026-09-17 on Windows 11, Node 24: `write_file` allowed and executed, `move_file` denied, no side effect |

## Supported

- **Protocol**: MCP as implemented by the official Python SDK 2.2.x
  (`mcp>=2.0`). The proxy is a lowlevel `Server`; the upstream is driven with
  `ClientSession`. Initialization/capabilities are negotiated by the SDK.
- **Transport**: stdio only, on both sides. No SSE, no Streamable HTTP.
- **Methods**: `tools/list` (filtered) and `tools/call`. Prompts, resources,
  sampling, elicitation, tasks and `input_required` results are **not**
  proxied; a tool that returns an `input_required` result is reported as
  `UPSTREAM_UNSUPPORTED_RESULT`.
- **Upstream launch**: any command + args; environment is the inherited
  default plus `upstream.env`; `cwd` optional. No upstream authentication is
  performed by the proxy (the upstream is a local subprocess).
- **Client configuration**: point your MCP client at
  `atp mcp-proxy --config atp-mcp.yaml` instead of the upstream command, and
  give it `ATP_AGENT_TOKEN` in its environment. Example for a Claude
  Desktop-style config:

```json
{
  "mcpServers": {
    "notes": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/agent-trust-plane", "atp", "mcp-proxy", "--config", "/path/to/atp-mcp.yaml"],
      "env": { "ATP_AGENT_TOKEN": "atpa_..." }
    }
  }
}
```

## Setup (persistent gateway)

```bash
uv run atp keygen --write .env          # once
uv run atp serve                        # gateway on 127.0.0.1:8000
# with the operator key from .env:
#   1. issue a credential for the agent:   POST /agents/notes-assistant/credentials
#   2. issue the human root grant + a grant to the agent: POST /delegations
uv run atp mcp-init                     # writes atp-mcp.yaml; fill in delegation_grant_id
ATP_AGENT_TOKEN=atpa_... uv run atp mcp-proxy --config atp-mcp.yaml
```

`uv run atp demo mcp` does all of this against an ephemeral gateway and
prints the resulting traces.

## Config reference (`atp-mcp.yaml`)

| Field | Meaning |
|---|---|
| `gateway` | Gateway base URL |
| `server_name` | Short name; envelopes use `tool: mcp.<server_name>` |
| `principal`, `agent` | Who the calls are for and who makes them; `agent` must match the credential |
| `delegation_grant_id` | Grant the agent acts under |
| `agent_token_env` | Env var holding the bearer credential (default `ATP_AGENT_TOKEN`) |
| `upstream.command/args/env/cwd` | How to launch the upstream |
| `tools[]` | Explicit mappings; anything else is denied |
| `tools[].mcp_tool` | Upstream tool name |
| `tools[].capability` | Capability the delegation must hold |
| `tools[].resource_template` | e.g. `note:{id}`; placeholders are argument names |
| `tools[].resource_arguments` | Arguments consumed by the template (removed from the envelope payload) |
| `expose_unmapped_tools` | Advertise unmapped tools anyway (calls still denied and recorded) |
| `request_timeout_seconds` | Upstream call timeout |

## Policies that apply

Every proxied call passes `delegation.valid`, `capability.required` and
`resource.scope` — that is: the agent's credential must be live, its chain
must be unexpired and unbroken, the mapped capability must be delegated, and
the argument-derived resource must be inside the delegated scope. The
payment-specific policies do not apply to `mcp.*` tools. A generic
argument-constraint policy (e.g. numeric limits for arbitrary tools) is on
the roadmap; today, resource scoping is the argument-aware control.

## What this protects and what it does not

**Gateway-mediated enforcement.** For a client that reaches the upstream
*through the proxy*, every call is decided by the gateway before the upstream
sees it, with a signed single-use grant binding the exact arguments, and the
outcome is recorded against that grant. Argument tampering between authorize
and forward is impossible because the proxy forwards the same arguments it
hashed; oversized arguments are refused rather than truncated.

**Not protected.**

- An agent that can launch or connect to the upstream server directly. The
  proxy is the enforcement point; `test_direct_upstream_access_is_not_protected`
  demonstrates the bypass on purpose. Deploy upstreams so that only the proxy
  can start or reach them.
- The proxy process itself. It holds the agent's bearer token and is trusted
  code on the agent host. If it is compromised, it can forward anything to
  the upstream it already launched (it cannot, however, mint grants or forge
  trace decisions).
- The upstream's own behaviour. A malicious upstream can return anything;
  the proxy relays results unchanged and records a bounded summary.
- Denial of service, rate limiting, concurrency across many proxies.

## Trace shape for a proxied call

```
action_proposed → delegation_resolved → policy_evaluated → decision_made
→ grant_issued → execution_attempted → execution_released → execution_completed|execution_failed
```

`execution_released` is the gateway handing the consumed grant to the proxy;
the final event is reported by the proxy (actor = the agent, with its
credential id) and is accepted exactly once per grant.
