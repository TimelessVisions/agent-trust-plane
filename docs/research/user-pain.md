# Developer pain around agent tool use (collected 2026-09-17)

Sources are issues, protocol proposals, vendor security notes and
published incident write-ups. One anecdote is not a trend; each item below
lists more than one independent source or an official protocol-level
proposal. Nothing here is a claim about ATP's users (there are none yet).

## Frequently observed pain

1. **Tool-level permission scoping is missing or coarse.**
   - MCP spec proposals SEP-1880 "Tool-level scope requirements" and
     SEP-1881 "Scope-filtered tool discovery" (modelcontextprotocol/
     modelcontextprotocol #1880, #1881): "nothing in the current schema
     allows tools to declare their expected scopes ahead of time".
   - TypeScript SDK #1582: per-operation scopes cause an infinite
     re-authorization loop.
   - mastra-ai/mastra #17508: "scope tool-authorization (FGA) independently
     of the instance-level agent tool mapping".
   - agentgateway #2069: arguments cannot be used in authorization.
   *What people want*: "this agent may call this tool on these resources
   with these limits", decided before the call.

2. **Destructive actions taken on injected instructions.**
   - Johns Hopkins researchers (2026-04) hijacked Claude Code, Gemini CLI
     and GitHub Copilot via PR titles, exfiltrating Actions secrets.
   - MCPoison (CVE-2025-54136): Cursor bound approval to a server's
     *name* rather than its contents.
   - Microsoft (2026-06), OWASP "MCP Tool Poisoning", CSA research note
     (2026-07): tool descriptions are an unsanitised attack surface.
   - Docker MCP Gateway's security model puts prompt injection out of
     scope; the damage bound has to come from somewhere else.
   *What people want*: the injected instruction must not be able to
   exceed what the human delegated, regardless of the model.

3. **Nobody can prove what an agent did.**
   - Docker MCP Gateway #557 asks for a tamper-evident record of tool
     calls; the default logger deliberately drops argument values.
   - Gateways log; none of them can re-evaluate a recorded call.
   *What people want*: an evidence artifact a reviewer can replay.

4. **Policy debugging is opaque.**
   - agentgateway #3092: rules that referenced arguments silently denied
     everything.
   - Cedar/OPA users routinely ask "why was this denied" (both projects
     ship diagnostics/`opa eval --explain` for this reason).
   *What people want*: the exact condition that failed, and the value it
   compared against.

5. **Turning on enforcement is scary.**
   - envoyproxy/gateway #10024 requests RBAC shadow/dry-run mode "as a
     safer rollout path"; mcp-airlock ships shadow tiers; gateway vendors
     advertise "audit mode" first.
   *What people want*: observe → decide what would have been blocked →
   enforce.

6. **Approval fatigue vs. autonomy.** IDE agents ask for approval on
   every tool call; users click through (the MCPoison lesson). Every
   vendor best-practice list says "require approval for high-consequence
   tools, autonomous for reads". Distinguishing reads from writes needs
   argument-level knowledge, not tool names.

## Emerging pain

7. **Multi-agent delegation.** A2A v1.0 (2026-04) makes agent → agent task
   delegation standard; "Governance Gaps in Agent Interoperability
   Protocols" (arXiv 2606.31498) argues MCP/A2A cannot express authority
   limits along a delegation. Nobody in the gateway space models
   attenuation.

8. **Evidence for compliance.** Vendor blogs (MintMCP, Maxim, Integrate.io)
   sell "SOC 2 for MCP" on audit logs. The demand is real; the artifacts
   are logs, not replayable decisions.

9. **Long-running and streaming tools.** With `input_required` results
   and tasks in the 2026-07-28 MCP revision, authorization at call start
   is no longer the whole story.

## Speculative future pain

10. Budgets over time (cumulative spend, rate) for agents that run for
    days — mentioned in vendor checklists, rarely in issues yet.
11. Cross-organisation agent identity (SPIFFE-style) for A2A.
12. Regulatory demand for "explainable automated decisions" applied to
    agent actions.

## Implications used in this pass

| Pain | Addressed by |
|---|---|
| 1 | delegation scopes incl. prefix scopes for paths; per-tool mapping generated from the server's own tool list |
| 2 | argument-aware decisions against delegated limits; unmapped/destructive tools fail closed |
| 3 | hash-chained trace, evidence export, replay |
| 4 | `atp policy explain` with the failing constraint and what would need to change |
| 5 | shadow mode declared by the gateway, never by the caller; `WOULD_DENY` in traces and CLI |
| 6 | mapping generated from `readOnlyHint`/`destructiveHint` as *proposals* the human reviews; annotations are never trusted as authority |
| 7 | delegation model already chains agent → agent; A2A mapping documented, not built |
