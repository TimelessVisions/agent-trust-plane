# Competitive research at code level (inspected 2026-09-17)

Extends `docs/research/competitive-landscape.md` (2026-09-16/17). Everything below
was checked against a repository, an official documentation page, an issue
tracker or a package index on the date given. Where a project was assessed
from documentation only, that is stated. Star counts and issue states are
from the GitHub API on 2026-09-17.

## 1. MCP / agent gateways

### agentgateway (solo.io) — 4,887 ★, Apache-2.0, pushed 2026-09-16

- **Core use case**: Rust data-plane proxy for MCP, A2A and LLM traffic;
  Kubernetes-native (Gateway API), federation, JWT/OAuth, OTel.
- **Auth/policy model**: CEL rules with `mcp.tool.name`, `mcp.tool.target`
  and JWT claims. Denied tools are filtered from `tools/list`.
- **Argument-aware decisions**: **No.** The MCP authorization page states:
  "`mcp.tool.arguments` is populated only after a tool call completes, so it
  cannot be referenced in mcpAuthorization rules" and recommends deciding on
  name and target. Feature request [#2069](https://github.com/agentgateway/agentgateway/issues/2069)
  ("Support tool arg MCP auth") is **open**, updated 2026-09-10.
- **Audit / replay / regression**: access logs; no decision replay; no test
  runner for policies against recorded calls.
- **Strongest**: transport breadth, performance, ecosystem (kgateway).
- **Weakest for our use case**: cannot express "pay ≤ $1,000 to an approved
  vendor"; no authority delegation model; no evidence artifact.
- **ATP better**: argument-aware, delegation-derived decisions; decision →
  execution binding; replay; regression suites.
  **ATP worse**: everything about being a production gateway.

### Stacklok ToolHive — 2,181 ★, Apache-2.0, pushed 2026-09-16

- **Core use case**: run MCP servers in containers with OIDC in front;
  Kubernetes operator; registry.
- **Policy model**: Cedar. Principal attributes from JWT claims
  (`claim_sub`, `claim_roles`, …); resource = tool.
- **Argument-aware**: **Partially.** Scalars become `arg_<key>` (String/
  Bool/Long/Decimal); "complex argument types (objects, nested arrays)
  cannot be represented directly in Cedar. Instead, ToolHive creates a
  boolean `arg_<key>_present`" ([policy reference](https://docs.stacklok.com/toolhive/reference/authz-policy-reference)).
  No notion of *delegated* limits: a Cedar policy can compare `arg_amount`
  to a literal, not to an authority resolved from a chain.
- **Testing / dry-run**: no dry-run, shadow or policy-testing feature in
  the reference.
- **Strongest**: real policy language with a mature evaluator; container
  isolation; enterprise identity.
- **ATP better**: authority as data (delegation chain) rather than
  literals in policy text; replay; regression. **ATP worse**: policy
  language expressiveness, identity provider integration, isolation.

### Docker MCP Gateway — 1,567 ★, MIT, pushed 2026-09-16

- **Core use case**: desktop/local gateway running MCP servers as
  containers, secrets scoping, image signature verification, interceptors
  (exec/http/docker).
- **Security model** ([docs/security.md](https://github.com/docker/mcp-gateway/blob/main/docs/security.md)):
  covers secret scoping, container isolation, signature verification;
  interceptors are trusted; **prompt injection and tool-description
  poisoning are explicitly out of scope** "unless it bypasses a gateway
  boundary".
- **Audit**: `--log-calls` records "tool name and argument shape metadata
  only. Raw tool-call argument keys and values must not be logged by the
  default call logger." Tamper-evident records are an **open** request
  ([#557](https://github.com/docker/mcp-gateway/issues/557), 2026-08-23).
- **Argument-aware policy**: only by writing a custom interceptor.
- **ATP better**: evidence with argument values (bounded, hash-chained),
  replay, regression. **ATP worse**: no isolation, no secrets management,
  no image verification. ATP could run *as* a Docker interceptor
  (`http` type) — the cleanest integration path, not built yet.

### IBM ContextForge (mcp-context-forge) — 4,483 ★, Apache-2.0, pushed 2026-09-16

- **Core use case**: enterprise registry + gateway for MCP/A2A/REST,
  40+ plugins, RBAC/teams, OTel.
- **Authorization**: effective tool grants are not yet enforced on
  `tools/call`: [#4647](https://github.com/IBM/mcp-context-forge/issues/4647)
  "[CF-DATAPLANE] Publish and enforce effective tool authorization grants"
  is **open** (updated 2026-08-20); the "Security Policy Engine" epic
  [#6408](https://github.com/IBM/mcp-context-forge/issues/6408) is **open**
  (updated 2026-09-07). 915 open issues overall.
- **ATP better**: a working, tested grant-binding path today. **ATP
  worse**: everything enterprise (multi-tenant, federation, UI, plugins).

### mcp-airlock (Shalimov04) — 24 ★, MIT, 2026-07-28

- Stateless Python/Starlette governance proxy for the 2026-07-28 MCP
  revision: four risk tiers (L0 read-only → L3 auto-execute), forced
  dry-run for dangerous tools, human confirmation, audit, OTel. Policy is
  flat YAML with per-principal overrides and a `count_arg` blast-radius
  limit.
- Closest small project in spirit. Differences: tiers are per tool, not
  per argument value; authority is per principal, not delegated and
  attenuated; no decision→execution binding; no replay or regression from
  recorded calls; forced dry-run "relies on tool implementation honesty"
  (their words). Worth citing as prior art for shadow/dry-run in an MCP
  proxy.

### Others seen, not inspected in depth

`mcp-gate` (Go, single-use HMAC capability tokens per route; token does
not commit to argument values), `secure-agent-gateway` (demo, inert tools),
several "zero-trust agent control plane" repositories with 0–19 stars
(`c2siorg/acf-sdk`, `realgradientdescent/agent-trust-control-plane`,
`r-aaron-graham/agent-trust-control-plane`). None offers replay or
regression from recorded decisions.

## 2. Policy / authorization systems (documentation-level assessment)

| System | What it is | Relevance to ATP | Verdict |
|---|---|---|---|
| **OPA / Rego** (12,240 ★) | General-purpose policy engine; `opa test`, `--coverage`, decision logs, bundles | The obvious "why not just OPA?" (see `docs/why-not-just-opa.md`). OPA answers a policy question given input; it has no notion of delegated authority, action binding, tool interception, or replay of an agent decision. | Adapter target (P2). Do not reimplement. |
| **Cedar** (1,737 ★) | Policy language with schema validation and formal analysis (Lean-verified evaluator, SMT-based policy analysis) | Same as OPA; stronger static analysis. Cedar's `cedar-policy-analysis` answers "does policy A permit more than policy B?" — the *policy-level* version of our impact analysis. Our impact analysis is *trace-level* (what recorded actions flip), which is the question an incident review asks. | Adapter target (P2). Cite for policy diff prior art. |
| **OpenFGA** (5,782 ★) / **SpiceDB** (7,057 ★) | Zanzibar-style relationship graphs | Model *who relates to what*; do not evaluate argument constraints or bind executions. Could host the "principal → resource" part of a scope. | Not now. |
| **AuthZEN** (OpenID) | Standard PDP request/response API (subject/action/resource/context) | ATP's `/authorize` is shaped like a PDP call with an envelope; an AuthZEN-compatible façade is cheap later. | P2. |
| **Macaroons** | HMAC-chained bearer tokens with caveats; offline attenuation | Our delegation grants are server-resolved records, not tokens; our execution grant is a single-use HMAC token. Macaroon-style offline attenuation would let agents delegate without the gateway, at the cost of revocation. | Design reference; rejected for now (revocation matters more than offline delegation for agents). |
| **Biscuit** | Public-key attenuable tokens with Datalog checks | Same trade-off as Macaroons with asymmetric keys. | Reference for asymmetric grants (O6). |
| **SPIFFE/SPIRE** | Workload identity (SVIDs), mTLS | The right "enterprise identity provider" behind an `IdentityProvider` interface. | Interface designed (Phase 21), not implemented. |

## 3. Agent security / evaluation

| Project | ★ | What it does | Overlap |
|---|---|---|---|
| promptfoo | 25,195 | Eval + red-team (YAML, plugins for excessive-agency, BOLA/BFLA, memory poisoning) | Discovers problems; enforces nothing; no runtime decision artifact. Complementary: promptfoo finds, ATP pins. |
| Inspect AI | 2,787 | Eval framework with tool-approval policies (glob on tool name, prefix match on the serialised call; approve/modify/reject/escalate) inside the harness | Approval is eval-time, not runtime; the match is string-prefix, not argument-typed. |
| AgentDojo | 836 | Prompt-injection benchmark for tool-using agents | Benchmark, not enforcement. Useful attack corpus. |
| PyRIT / garak | — | Model red-teaming frameworks | Content/model layer, not action layer. |
| OWASP | — | "MCP Tool Poisoning" attack page; agentic guidance | Confirms tool descriptions are an attack surface (we treat them as untrusted metadata). |
| "Before the Tool Call" (Uchibeke, arXiv 2603.20953, 2026-03) | — | Open Agent Passport: synchronous pre-action authorization against declarative policy with signed audit records; 4,437 decisions in an adversarial testbed | Academic validation of the pre-action, deterministic approach. No replay/regression, no delegation attenuation reported in the abstract. |
| Mutation testing of access-control policies (Martin & Xie 2007; Xu et al. SACMAT 2020) | — | Mutate the *policy* and derive requests that distinguish mutants | Prior art. Our `atp mutate` mutates the *recorded request* to probe a fixed policy; it is request-side fuzzing with domain mutators, not policy mutation. We must not call it novel. |

## 4. Agent runtimes / frameworks

| Framework | Hook available for pre-tool authorization (verified in docs) | Fit |
|---|---|---|
| OpenAI Agents SDK (Python) | `@tool_input_guardrail` → `ToolGuardrailFunctionOutput.allow / reject_content / raise_exception`; `RunHooks.on_tool_start` raising cancels the tool | Decision-only integration (the SDK executes the tool itself, so ATP's grant binding cannot be preserved). Adapter deferred; see rejected ideas. |
| LangGraph | `interrupt()` before a tool node (human-in-the-loop) | Same shape: decision hook, no execution binding. |
| MCP clients (Claude Desktop, Cursor, VS Code, Claude Code) | stdio server config; Streamable HTTP for remote | The proxy path: no code change to the agent. This is why the MCP proxy is the one integration we build well. |
| A2A v1.0 (Linux Foundation, 2026-04; 1.0.1 extensions 2026-05) | Task delegation between agents | See `docs/research/agent-to-agent-future.md`. |

## 5. Observability

OpenTelemetry GenAI semantic conventions moved to
`open-telemetry/semantic-conventions-genai`; status **Development**;
`gen_ai.operation.name = execute_tool`, `gen_ai.tool.name`, and an MCP
conventions page (`mcp.method.name`, `mcp.session.id`, span name
`{mcp.method.name} {target}`), all Development. Exporting ATP events as
spans is straightforward; the conventions are not stable, so this is P1.

## 6. Developer tooling

- JUnit XML: consumed natively by GitHub Actions reporters, GitLab, Jenkins.
  Already produced.
- SARIF: a *static analysis* result format (rules, locations in files).
  Authorization regressions have no file location; a suite case could be
  mapped to a `region` in the YAML, which is semantically a stretch. See
  the decision in `docs/adr/0003-category-definition.md`: JUnit + JSON,
  no SARIF.
- `pre-commit`: `atp test` is fast enough (≈1 s per suite) to run as a
  hook; documented, not packaged as a hook repo.

## What ATP does better / worse (summary)

Better, with evidence in this repository: argument-aware decisions derived
from a delegation chain; hash-bound single-use execution grants; hash-
chained evidence with replay under another policy version; trace → CI
regression; an MCP proxy that needs no server modification.

Worse: policy language (Python classes until this pass; a small
declarative format after it), identity integration, transports,
isolation, federation, UI maturity, community size (zero users).
