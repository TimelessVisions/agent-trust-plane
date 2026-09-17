# Competitive landscape — agent tool authorization and evaluation

Researched 2026-09-16/17 by inspecting repositories, documentation, issue
trackers and release pages directly (GitHub API and web). Star counts and
dates are as observed on 2026-09-17. Nothing below is inferred from marketing
copy alone; where a claim comes from a competitor's own limitation statement
or an open issue, the link is given.

## Summary table

| Project | What it is | Stars / last push | Tool-call authorization | Argument-aware at decision time | Audit | Policy regression testing / replay |
|---|---|---|---|---|---|---|
| [IBM ContextForge](https://github.com/IBM/mcp-context-forge) | MCP/A2A/REST registry + gateway, 40+ plugins, OTel | 4,482 / 2026-09-16; 1.0.10 (2026-09-07) | Auth (basic/JWT/OAuth), RBAC/teams; effective tool grants **not yet enforced on `tools/call`** per [#4647](https://github.com/IBM/mcp-context-forge/issues/4647) (open) | Not a documented feature; "Security Policy Engine" is an open epic [#6408](https://github.com/IBM/mcp-context-forge/issues/6408) (2026-08-25) | OTel tracing, logs | No |
| [agentgateway](https://github.com/agentgateway/agentgateway) (solo.io) | Rust proxy for MCP/A2A/LLM; CEL RBAC; JWT/API key/OAuth; OTel | 4,886 / 2026-09-16; v1.5.0 (2026-08-27) | CEL rules on `mcp.tool.name`, `mcp.tool.target`, JWT claims; denied tools filtered from `tools/list` ([docs](https://agentgateway.dev/docs/standalone/main/documentation/configuration/security/mcp-authz/)) | **No.** `mcp.tool.arguments` is post-request/log only; the docs say to "base decisions on tool name and target instead". Feature request open: [#2069 "Support tool arg MCP auth"](https://github.com/agentgateway/agentgateway/issues/2069) (2026-06-04); [#3092](https://github.com/agentgateway/agentgateway/issues/3092) fixed rules that referenced arguments and silently denied everything | Access logs with arguments/results | No |
| [Stacklok ToolHive](https://github.com/stacklok/toolhive) | Runs MCP servers in containers; OIDC; Cedar authorization; OTel/Prometheus | 2,181 / 2026-09-16; v0.49.0 (2026-09-11) | Cedar policies: principal (JWT `sub`), action (`call_tool`), resource (tool) | **Partially.** Scalar arguments are exposed as `arg_<key>` (string/bool/long/decimal); objects/arrays only as `arg_<key>_present` ([policy reference](https://docs.stacklok.com/toolhive/reference/authz-policy-reference)) | Audit logging via OTel | No dry-run/testing documented |
| [Docker MCP Gateway](https://github.com/docker/mcp-gateway) | Local/desktop gateway running MCP servers in containers; secrets scoping; signature verification; interceptors | 1,567 / 2026-09-16; v0.43.3 | Server/tool enable lists; custom before/after/around interceptors (exec/http/docker) | Via custom interceptor code only; no policy language | `--log-calls` records tool name + argument *shape* only by design ([security.md](https://github.com/docker/mcp-gateway/blob/main/docs/security.md)) | No. Tamper-evident record proposal is an open issue [#557](https://github.com/docker/mcp-gateway/issues/557) (2026-08-22). Prompt injection is explicitly **out of scope** of its security model |
| [mcp-gate](https://github.com/ananthaprakashb/mcp-gate) | Small Go reverse proxy; single-use HMAC capability tokens bound to route/method/path; closed-schema JSON validation | 0 / 2026-08-25 | Capability token per HTTP route | Schema-validated, but "the token does not currently commit to the exact argument values" (README) | Not a feature | No |
| [secure-agent-gateway](https://github.com/jspillers10/secure-agent-gateway) ("agent authorization gateway" pattern) | Vertical-slice demo: RS256 delegated identity, OPA, single-use approvals, redacted audit, Docker worker | 0 / 2026-09-08; 4 commits, 59 tests | OPA policy + registry cross-check | Pydantic `extra=forbid` argument validation | Hash-redacted audit | No; "all tools are inert mocks"; no MCP or framework integration |
| [promptfoo](https://github.com/promptfoo/promptfoo) | LLM eval + red-team; YAML tests; plugins (rbac, bola, bfla, excessive-agency, memory-poisoning, rag-poisoning); OTel traces | 25,186 / 2026-09-17; 0.123.0 (2026-09-10) | **Evaluation only** — finds problems, does not enforce ([agents guide](https://www.promptfoo.dev/docs/red-team/agents/)) | n/a | Trace capture for grading | Red-team scenario generation, not replay of a recorded authorization decision |
| [Inspect AI](https://inspect.aisi.org.uk/) (UK AISI) | Eval framework; tasks/solvers/scorers; sandboxes; **tool approval policies** (human/auto approvers, glob on tool name + prefix match on arguments, approve/modify/reject/escalate/terminate) ([approval docs](https://inspect.aisi.org.uk/approval.html)) | 2,786 / 2026-09-17 | Approval inside the eval harness only | Prefix string match on serialised call, e.g. `computer(action='key'` | Eval logs | Evaluation harness; not a runtime gateway |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) (ETH) | Benchmark for prompt-injection attacks/defenses on tool-using agents (NeurIPS 2024) | 835 / 2026-06-02 | None (benchmark) | n/a | n/a | Benchmark harness, not enforcement or regression testing |

## What they already solve (do not rebuild)

- **Running and federating MCP servers**: ContextForge, agentgateway, ToolHive
  and Docker MCP Gateway all do transport translation, server lifecycle,
  container isolation, secrets injection, OAuth/JWT at the front door, and
  OpenTelemetry. This is mature, multi-thousand-star territory.
- **Coarse tool RBAC**: "user X may call tool Y" is solved by agentgateway
  (CEL), ToolHive (Cedar), ContextForge (teams/RBAC, in progress for
  `tools/call`).
- **Finding vulnerabilities in agents before deployment**: promptfoo's
  red-team plugins and AgentDojo's benchmark cover injection discovery far
  more broadly than a hand-written eval suite.
- **Human-in-the-loop approval inside evals**: Inspect's approval policies.

## What developers struggle with (from issues and docs)

1. **Deciding on arguments, not just tool names.** agentgateway cannot do
   it ([#2069](https://github.com/agentgateway/agentgateway/issues/2069));
   ToolHive can for scalars only; Docker requires writing an interceptor;
   ContextForge's policy engine is an open epic. Yet the attacks that
   matter (pay $12,500 instead of $480; send to a different account) are
   *argument* attacks with a permitted tool name.
2. **Tamper-evident records of what agents actually did** — an explicit
   request on Docker MCP Gateway ([#557](https://github.com/docker/mcp-gateway/issues/557)),
   and Docker's default logger deliberately drops argument values.
3. **Authority that is derived from delegation, not from a static role.**
   Every gateway above models "principal → tool" but not "human → orchestrator
   → worker with attenuated limits". ContextForge's
   [#4647](https://github.com/IBM/mcp-context-forge/issues/4647) is about
   publishing *effective* grants, which is the same problem stated from the
   enterprise side.
4. **Proving a policy change fixes a specific incident.** None of the
   gateways offer replay of a recorded decision under a new policy, and none
   of the eval frameworks offer a runtime-enforceable policy. Developers get
   either "promptfoo found it" or "the gateway now blocks tool X" — not "this
   exact recorded call is now denied, and CI will keep it that way."
5. **Prompt injection is out of scope for the gateways.** Docker says so in
   its security model; the others treat it as a content-filter/guardrail
   concern. What a gateway *can* do about injection — bound the damage by
   authority — is not framed that way.

## What they do better than us

- Transports, federation, container isolation, secrets, OAuth, OTel, Helm,
  UIs: all of them, by a wide margin. We should not compete on this and
  should be able to sit *behind* them.
- Policy languages: CEL and Cedar are real languages with tooling; our
  policies are Python classes. For a developer tool this is a gap; for
  correctness it is also an advantage (policies are unit-tested code).
- Community and maturity: thousands of stars, daily commits, release trains.
- Vulnerability *discovery* breadth: promptfoo and AgentDojo.

## Where our architecture has a defensible advantage

Verified against our code, not asserted:

1. **Argument-aware, delegation-derived authorization.** Our policies
   evaluate amount, currency and destination against an *effective* limit
   computed by intersecting a delegation chain rooted at a human. That is
   the missing piece in #2069 / #4647 and the scalar-only Cedar exposure.
2. **Decision → execution binding.** A signed, single-use, audience-bound
   grant carrying the hash of the exact action. mcp-gate's token does not
   commit to argument values; the gateways above authorize the request in
   flight without a reusable, inspectable artifact.
3. **Hash-chained trace + replay under a different policy version.** The
   thing Docker #557 asks for, plus the ability to re-run the recorded
   decision. Nobody in the table offers replay.
4. **Regression tests from traces.** Turning "this happened" into "CI fails
   if this is ever allowed again" is absent from every project above; the
   eval frameworks generate attacks, they do not pin decisions.

## Where our positioning must change

- We are **not** an MCP gateway and should stop implying we could be one.
  We are an authorization decision + evidence layer that can run *inside* or
  *beside* those gateways (as an interceptor, an ext_authz, or an MCP proxy
  for local development).
- Our own MCP integration must be honest about scope: a stdio proxy for a
  single upstream server is a development and testing tool, not a
  production gateway.
- "Security" in our name should mean **bounded authority + proof**, not
  content filtering, secrets scanning, or container isolation.

## Sources

- IBM ContextForge README and issues #4647, #6408 — https://github.com/IBM/mcp-context-forge (2026-09-16)
- agentgateway README, MCP authorization docs, issues #2069, #3092 — https://github.com/agentgateway/agentgateway, https://agentgateway.dev/docs/standalone/main/documentation/configuration/security/mcp-authz/ (2026-09-16)
- ToolHive README and authorization policy reference — https://github.com/stacklok/toolhive, https://docs.stacklok.com/toolhive/reference/authz-policy-reference (2026-09-16)
- Docker MCP Gateway security model and issue #557 — https://github.com/docker/mcp-gateway/blob/main/docs/security.md (2026-09-16)
- mcp-gate README — https://github.com/ananthaprakashb/mcp-gate (2026-09-16)
- secure-agent-gateway README — https://github.com/jspillers10/secure-agent-gateway (2026-09-16)
- promptfoo agent red-teaming guide — https://www.promptfoo.dev/docs/red-team/agents/ (2026-09-16)
- Inspect AI approval docs — https://inspect.aisi.org.uk/approval.html (2026-09-16)
- AgentDojo README — https://github.com/ethz-spylab/agentdojo (2026-09-16)
- Star counts, push dates, release tags via GitHub API on 2026-09-17.
