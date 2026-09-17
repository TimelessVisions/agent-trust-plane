# Rejected and deferred ideas (v0.3.0 pass)

The mission brief listed ~90 design phases. This is the classification
after research and red-teaming. Only P0 was built; P1/P2 are on the
roadmap; RESEARCH items have a note; REJECT items say why.

Reasons: *duplicates mature tool* · *weak demand* · *too much complexity* ·
*wrong layer* · *premature* · *unsafe* · *not differentiated*.

## Built (P0)

One-command MCP wrapping with in-process gateway (`atp mcp init/wrap`);
local-first store (`.atp/`); prefix/path scopes with normalisation;
declared policy sets; shadow mode; `policy explain/diff/impact/coverage`;
offline `mutate`; `regression add` from the local store; evidence
bundles; Streamable HTTP *upstream*; property-based and exhaustive
state-machine tests; `IdentityProvider` boundary; single distribution
installable with `uvx`; docs IA; CI hardening.

## P1 (next)

| Idea | Why not now |
|---|---|
| Streamable HTTP *served* by the proxy, with client auth | Needs a client-auth story (bearer or OAuth) on the proxy's own endpoint; without it, serving HTTP widens the boundary. Upstream HTTP covers remote servers today. |
| OpenTelemetry export of decisions as `execute_tool` spans | Conventions are *Development* status (checked 2026-09-17); adds a dependency; nothing in the loop needs it. Export never becomes the source of truth. |
| Idempotency-key injection into upstream arguments | Needs per-tool knowledge of the argument name; a mapping option is the right shape. |
| Signed trace heads / external checkpointing | Only meaningful with a separate gateway service and a KMS (`trace-integrity.md`). |
| `IdentityProvider` selection from settings; SPIFFE/OIDC providers | Interface exists; providers need a deployment to test against. |
| Postgres stores | One-node lock is documented; nobody has asked. |
| Docker Compose (gateway + dashboard + notes server) | Not needed for the loop; `atp mcp wrap` is zero-infra. Listed for people who want `atp serve` in a container. |

## P2 (valuable extension)

OPA / Cedar policy adapters; AuthZEN façade; Docker MCP Gateway
interceptor and agentgateway ext-authz modes; TypeScript SDK; dashboard
policy-impact view; `atp test --changed` (PR-diff selection of cases).

## RESEARCH

| Idea | Note |
|---|---|
| Budgets and quotas over time | Correct atomic consumption across concurrent authorizations needs a reservation step (`authorize` reserves, `execute` commits, expiry releases) and a single writer. Doing it without the reservation would race; not shipped rather than shipped wrong. Design sketch: a `budget` constraint on a grant (`max_total_amount`, `max_actions`, `window`) with reservations stored beside grants. |
| Human approval protocol | Design: `REQUIRE_APPROVAL` → approver (an authenticated principal with an `approve:` capability) signs `(action_hash, trace_id, expires)` → re-authorization presents the approval → grant. A changed action invalidates the approval by hash. Not built: needs approver identity, which needs per-human credentials (O11). |
| A2A delegation | `research/agent-to-agent-future.md`. |
| Policy mutation testing (mutating the policy, not the request) | Prior art exists (XACML); would need a policy AST; our declared format is small enough that request-side mutation covers the practical cases. |
| Security graph visualisation | Only if delegation chains get deeper than three links in practice. |
| Name change | PyPI `atp`/`atp-core` collide with unrelated projects; the distribution is `agent-trust-plane`; the `atp` CLI collides with nothing current (Debian's `atp` was removed). No rename. |

## REJECT

| Idea | Reason |
|---|---|
| A richer policy DSL (expressions, regex, time windows) | *duplicates mature tool* (OPA/Cedar), *unsafe* (regex on untrusted input). Eight rule kinds is the cap. |
| Five framework adapters (OpenAI Agents, LangGraph, CrewAI, AutoGen, …) | *not differentiated*, *wrong layer*: those hooks are decision-only (the SDK executes the tool itself, so no grant binding). One good protocol-level integration beats five thin ones. Documented in `integrations/frameworks.md`. |
| SARIF output | *wrong layer*: SARIF describes findings at code locations; a regression is a test result. JUnit + JSON. |
| GitHub Marketplace Action | *premature* until pinned, reviewed and there are users; a composite action example ships in the repo instead. |
| Fake SSO / RBAC / multi-tenancy / billing | *enterprise theater*; nothing in the wedge needs it. |
| Product telemetry | zero telemetry; opt-in only if ever proposed. |
| Dashboard investment | frozen at before/after evidence; the CLI is the product surface. |
| Screen recording tooling in the repo | no recording software is available in the maintainer environment; `scripts/record-demo.py` captures a real transcript instead of faking a GIF. |
| Renaming import packages to `atp.*` | churn across the whole tree for a collision that only bites if the Attested Transport Protocol SDK is installed in the same environment; documented instead. |
| Macaroon/Biscuit-style offline delegation | *premature*: revocation and evidence matter more than offline attenuation for agents; kept as a design reference. |
| Kubernetes / Helm | *premature*. |
