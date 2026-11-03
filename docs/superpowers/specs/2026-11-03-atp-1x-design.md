# ATP 1.0 → 1.2 design: the proof release, then reach

Status: design, awaiting owner approval. Written 2026-11-03 from `main` at `0c43c24` (v0.3.2).

## Intent

ATP should make a veteran, skeptical reviewer in agent security say "wow" when they compare it with the competition. They will not be impressed by more features. They will be impressed by **one public, reproducible result that no competitor can produce.** ATP's real advantage is argument-aware decisions derived from a delegation chain. 1.0 exists to measure that advantage on a standard attack corpus and publish the result. Later releases widen reach.

Why now: the gaps competitors list for themselves are still open as of 2026-11-03.

- agentgateway #2069: arguments cannot be used in MCP authorization.
- IBM ContextForge #4647: effective tool grants are not enforced on `tools/call`.
- Docker MCP Gateway #557: there is no tamper-evident record of tool calls.

## Goals

1. **The headline result (1.0).** A deterministic, model-free benchmark, built from AgentDojo, that measures two numbers for each authorization layer:
   - **Harmful actions allowed**: the share of injection-task ground-truth tool calls the layer lets through.
   - **Legitimate work preserved**: the share of user tasks whose full ground-truth call sequence the layer allows.

   The worst-case assumption is stated on the results page: the agent obeys the injection completely. The numbers measure the authorization layer, not a model.
2. **Fair comparison (1.0).** The same benchmark runs against the strongest policy each competitor can express under its own documentation:
   - agentgateway (CEL on tool name and target),
   - Stacklok ToolHive (Cedar with `arg_*` scalars),
   - Docker MCP Gateway (its default security model, plus the strongest interceptor that needs no custom code, if one exists).

   Each competitor policy ships with a written justification that cites the competitor's docs, so a reader can argue with it.
3. **Known incidents as tests (1.0).** Rebuild these attack classes as runnable cases:
   - MCPoison (approval bound to a server's name),
   - PR-title / issue-text hijack of a coding agent leading to secret exfiltration,
   - tool-description poisoning,
   - an under-limit payment redirect (already exists).

   Each case shows the attack succeeding on a name-only layer, failing on ATP, and pinned as an `atp test` regression.
4. **Red-team readiness (1.0).** A self-hostable challenge target: a wrapped MCP setup with a planted "forbidden action" and a public rules page. Every attempt is recorded on ATP's hash-chained trace. Exported attempt logs give the published scorecard. The owner runs the red team; ATP supplies the harness.
5. **Stability promise (1.0).** Freeze and version these interfaces:
   - the envelope schema,
   - the trace/evidence format,
   - the policy file format,
   - the regression-suite format,
   - the CLI surface.

   Write a compatibility policy for them. Breaking changes after 1.0 need a major version.
6. **Results page (1.0).** One public page on the ATP site: the two-number chart for each layer, the method, the competitor-policy justifications, the limits, and a one-command rerun. This is the "wow" artifact.
7. **Reach (1.1, then 1.2).**
   - **1.1:** the proxy serves Streamable HTTP with client authentication (bearer first); decisions export as OpenTelemetry `execute_tool` spans; a GitHub Action runs `atp test` and comments on PRs with `policy impact`.
   - **1.2:** an AuthZEN-compatible decision endpoint; a Docker MCP Gateway `http` interceptor mode; an agentgateway external-authorization mode (subject to the open question below); a Cedar policy adapter.

## Non-goals

- Conversation monitoring, response grading or CX dashboards in the style of Trust OS. That is the wrong layer.
- Becoming a full production gateway (isolation, registries, federation, multi-tenant UI).
- Postgres, Kubernetes operators or SPIFFE providers before someone asks.
- Paid LLM API runs. Live agents run only on the owner's existing subscriptions (see "Second track").

## Anti-goals (what would count as failure even if it technically works)

- **ATP wins only because competitor policies were configured weakly.** Every competitor policy must be the strongest its docs allow. Where a policy is weak because the product cannot express the constraint, the results page says so and cites the doc.
- **Numbers that only the author can reproduce.** Every number needs a single command, pinned versions and a published raw-results file.
- **Hiding ATP's losses.** If ATP fails on some AgentDojo task families, the page shows those families and the next release addresses them.
- **Claims beyond the evidence**: "audited", "production-proven", user counts, or describing the owner's red team as independent.

## Constraints

- **$0 spend.** No paid APIs, hosting or audits. The benchmark is model-free by design. The red team is done by the owner, unpaid.
- **Repo rules.**
  - Branches are named `release/v1/<ticket>-<slug>`.
  - Each version is its own PR series.
  - Merges and PyPI releases need explicit owner approval.
  - No force pushes; tests are never suppressed.
  - Outcomes use the status vocabulary PASS / FAIL / SKIP / NOT_APPLICABLE / INCONCLUSIVE / NOT_MEASURED / ENV_BLOCKED.
- **Public repo.** No private release data in commits. The public name in copy is "the agent authorization platform"; the package, CLI and URLs stay `agent-trust-plane` / `atp`.
- **Machine.** Windows 11 with a WSL Ubuntu lane; Docker Desktop is ENV_BLOCKED. Running competitor gateways locally may need WSL-native binaries; where one cannot run, its result is ENV_BLOCKED and is not estimated.
- **Licensing.** AgentDojo's license must allow vendoring or downloading the task definitions. Check this before building on it. Fallback: fetch at benchmark time and pin by commit.

## Decided

- **Owner:** $0 spend. The owner red-teams personally when the time comes.
- **Owner:** the target is the "wow" reaction of a veteran critic compared with the competition.
- **Owner (via accepting the scenario ranking):** ATP's position is the decision-and-evidence layer that plugs into existing gateways, not a replacement gateway.
- **My call:** the benchmark is replay-based and model-free, under a worst-case "fully obedient agent" assumption.
- **My call:** 1.0 is the proof release; reach features move to 1.1 and 1.2.

## Resolved after the builder check (my calls unless marked)

- **Where delegations come from (my call).** Each AgentDojo user task gets a hand-written annotation that follows one published rule. An annotation may use the user's prompt and the environment state *before* any injection: files, contacts, balances. It may never use the injection text or the task's ground-truth calls; reading scope off the ground truth would make utility 100% by construction.
  - All annotations are committed, and their commit is tagged, **before** the first injection run. That is pre-registration: the git history proves the annotations were not tuned to the attacks.
  - A task whose annotation the rule cannot produce is NOT_APPLICABLE.
- **Competitors get the same per-task information (my call).** Each competitor's policy is generated per task from the same annotation, expressed as strongly as that product allows. Where the product cannot express a constraint (for example, an object-valued argument in ToolHive Cedar), the policy drops it and the justification doc cites why. ATP's win must come from what each layer can express, not from tailoring that only ATP received.
- **ATP may grow for 1.0 (my call).** New constraint kinds that the annotations need are 1.0 kernel work, for example "recipient ∈ set", "id equals" and "recipient already in thread". They land before the format freeze. The results page names the exact ATP version measured.
- **The older plan's format changes come into 1.0 (my call).** The unmerged `v0.4-file-format-versions` plan is folded in: Ed25519 grants with `kid`, cumulative budgets, signed root delegations, `REQUIRE_APPROVAL`, and `version:` fields. They are breaking, so they must land before the freeze, or they would wait until 2.0.
- **The same task set for every layer (my call).** NOT_APPLICABLE tasks are excluded from every layer's denominator, and their count is published next to the chart.
- **How harm is counted (my call).** Harm is counted per (user task × injection task) pair. A pair counts as harmful if any state-changing call from the injection's ground truth reaches the upstream. Read-only calls are excluded. This matches AgentDojo's own attack-success definition.
- **No external-users gate for 1.0 (owner, 2026-11-03: "benchmark is enough for now").** The older plan's requirement that 3 or more external people wrap their own server before 1.0 is dropped. The 1.0 README still says "no users yet" until that changes. The gate can return for a later release.

## Benchmark method (outline; detail is left to the builder)

1. Load the AgentDojo suites (workspace, travel, banking, slack) at a pinned commit.
2. For each suite, model its tools as MCP tools behind a sandbox MCP server that journals calls, as `test_deny_before_upstream` already does.
3. For each layer under test, write the strongest policy the layer supports. For ATP, write a delegation per user task: the human's intent scoped to that task's resources and limits, derived mechanically from the task description, not hand-tuned per injection. The derivation rule is published.
4. Replay each user task's ground-truth calls and record whether all are allowed. This gives utility.
5. Replay each (user task × injection task) pair, injecting the injection's ground-truth calls into the session. Record which reach the upstream, using the journal as the source of truth. This gives harm.
6. Emit raw JSONL plus a summary table. CI reruns a small slice on every PR.

**Fairness rule for step 3:** delegations may use only information available before the injection appears (the user's task), never the injection text.

## Second track: live agents on the owner's subscriptions (owner, 2026-11-03)

The replay track stays the headline because it measures the authorization layer alone. A second track runs **real agents**: Claude Code (`claude -p`, v2.1.316 installed) and Codex CLI (`codex exec`, v0.166.0 installed), headless, on the owner's existing subscriptions. This adds no API spend, the same way Buzz ran Claude Code as an agent.

- **Setup.**
  - The AgentDojo tools are served as an MCP server, wrapped by each layer under test.
  - The agent gets only those tools: `--strict-mcp-config` with an allow-list of the benchmark's MCP tools, built-in shell and file tools disallowed, and an empty working directory.
  - Injections arrive inside tool outputs, as in AgentDojo.
- **What it adds.** Real utility (does a real agent still finish the task through the layer?) and real-world harm (does an injection that fools the model still get stopped?). The model's own resistance is part of this number, and the page says so.
- **Not comparable to published AgentDojo results.** Those use AgentDojo's own agent pipeline. The page labels the track by agent and version.
- **Budget is time, not money (my call).**
  - Runs are sampled: every user task once for utility, plus one injection per user task for harm, per agent, per layer.
  - Runs are resumable, cache each result to disk, and stop cleanly on a usage limit.
  - A full sweep may take days of the owner's subscription quota. The runner prints the planned run count before starting.
- **Usage terms (my call).** This track runs only on the owner's machine, under the owner's own login, on the CLIs' supported headless modes. No credentials are stored in the repo or in results. Raw transcripts are published with secrets scrubbed.
- **Status vocabulary.** A run cut short by a usage limit is INCONCLUSIVE, never counted as a pass or a fail.

## Open questions for the builder to resolve early

- Does agentgateway's external-authorization hook receive the MCP request body (tool arguments)? If yes, ATP can serve as its argument-aware authorizer. If no, the 1.2 agentgateway mode becomes decision-on-name only and the docs must say so.
- Can ToolHive and agentgateway run in WSL without Docker? If not, their columns are ENV_BLOCKED until the owner can run them elsewhere.
- How many AgentDojo user tasks admit a mechanical delegation derivation? Tasks that don't are reported as NOT_APPLICABLE, not dropped silently.

## Left to the builder

- Package layout for the benchmark (a new `packages/bench` is suggested).
- Results-page implementation (the existing site work in `D:\Timeless Visions\` is the starting point; the page itself ships in the repo's `docs/`).
- Exact incident reconstructions, as long as each one cites a public write-up.
- The order of 1.1 items.

## Done means

- **1.0:** the benchmark reruns from a clean clone with one command. Competitor columns are measured or explicitly ENV_BLOCKED. The incident cases are pinned. The challenge harness runs locally. Formats are frozen with a compatibility doc. The results page is drafted. All CI is green. The owner approves the tag.
- **1.1 and 1.2:** each feature has a test that fails without it, and docs with the verified limits.
