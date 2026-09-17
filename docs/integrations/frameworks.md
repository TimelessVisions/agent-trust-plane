# Framework integration

The rule: **do not rewrite your agent**. Two ways to get ATP in front of it.

## 1. Protocol-level (recommended): the MCP proxy

If your agent reaches tools through MCP, point the client at
`atp mcp wrap` instead of the server. No agent code changes; every
`tools/call` is decided, bound and recorded. This is the integration ATP
builds well and tests against real servers ([mcp-proxy.md](mcp-proxy.md),
[compatibility.md](compatibility.md)).

Client configuration is the usual MCP stdio entry, for example:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "atp",
      "args": ["mcp", "wrap", "--config", "/abs/path/atp-mcp.yaml"]
    }
  }
}
```

(`uvx --from agent-trust-plane atp …` once the package is published; until
then `uv run --project <clone> atp …` or an installed wheel.)

## 2. Decision-only hooks (documented, not shipped)

Frameworks that execute tools themselves offer a pre-tool hook. ATP can
*decide* there, but cannot *bind* execution: the framework runs the tool
function after the hook returns, so the single-use grant is never
presented and exactness is not enforced. Use these for observation,
shadow-style evaluation, or when the tool function itself calls
`client.execute(...)`.

| Framework | Hook (verified in docs, 2026-09-17) | What ATP can do there |
|---|---|---|
| OpenAI Agents SDK (Python) | `@tool_input_guardrail` → `ToolGuardrailFunctionOutput.allow / reject_content / raise_exception`; `RunHooks.on_tool_start` raising cancels the tool | build an envelope from `ToolContext` (tool name, arguments JSON), call `/authorize`, reject on DENY; the trace records the decision |
| LangGraph | `interrupt()` before a tool node; custom tool-node wrapper | same shape |
| CrewAI / AutoGen | tool callbacks / wrappers | same shape |

A 40-line example of the OpenAI guardrail shape (not a supported adapter):

```python
from agents import tool_input_guardrail, ToolGuardrailFunctionOutput
from atp_adapter_http import TrustPlaneClient
from atp_core import ActionEnvelope

client = TrustPlaneClient("http://127.0.0.1:8000", agent_token=TOKEN)


@tool_input_guardrail
async def atp_guard(data):
    args = json.loads(data.context.tool_arguments or "{}")
    env = ActionEnvelope(
        principal=HUMAN,
        agent=AGENT,
        delegation_grant_id=GRANT,
        capability="fs:write",
        tool="fs",
        action=data.context.tool_name,
        resource=f"path:{args['path']}",
        arguments=args,
    )
    result = client.authorize(env)  # decision + trace; no grant is consumed here
    if result.execution_grant is None:
        return ToolGuardrailFunctionOutput.reject_content(result.decision.explanation)
    return ToolGuardrailFunctionOutput.allow()
```

This is decision-only. To get binding, make the tool function call
`client.execute(env, result.execution_grant)` and have the gateway own the
side effect (an external executor pattern), which is what the MCP proxy
does for you.

## 3. Your own code: the HTTP client

`atp_adapter_http.TrustPlaneClient`: `authorize(envelope)`,
`execute(envelope, grant)`, `report_outcome`, `get_trace`, `replay`, plus
operator calls. Synchronous; an in-process ASGI mode exists for tests and
for `atp mcp wrap`. An async client and a typed `trace(id)` are on the
roadmap; the surface above is what `atp` itself uses.
