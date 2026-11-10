# ATP 1.0.0 — Evidence-First Completion Runbook

**Status:** living implementation runbook; not a replacement for the approved spec, plan, or owner handoff.  
**Work branch:** `release/v1/B12-atp-1.0` (stacked on B11); **never `main`**.  
**Project:** the agent authorization platform (`agent-trust-plane` package and `atp` CLI).  
**Objective:** one public, independently reproducible *proof release*, not a general-purpose enterprise gateway.  
**Budget:** $0.  
**Binding authority, in order:** `docs/superpowers/specs/2026-11-03-atp-1x-design.md`, `docs/superpowers/plans/2026-11-04-atp-1.0.0.md`, `docs/superpowers/handoff/2026-11-05-handoff-to-1.0.0.md`, `docs/superpowers/handoff/2026-11-05-sdd-ledger.md`. The annotation rule and recorded amendments also bind benchmark work.

> If this document differs from a binding document, **follow the binding document** and record the conflict in the ledger. Mark every finding with one of PASS / FAIL / SKIP / NOT_APPLICABLE / INCONCLUSIVE / NOT_MEASURED / ENV_BLOCKED.

## 1. Release thesis and acceptance contract

The v1.0.0 argument to a skeptical reviewer is a **deterministic model-free benchmark** proving precisely what an authorization layer permits and denies, with reproducible hostile examples, faithfully configured competitor policies, incident reconstructions, and evidence-backed security regressions. Its reported two-number result is **harmful actions allowed** versus **legitimate work preserved** (including utility under attack where available). Report per-suite results, denominators, exclusions, approximations, policy-renderer source, version pins, and *raw* measurements. Do not infer security guarantees from tool-count pass rates.

**V1 in scope:** AgentDojo replay corpus and strongest-per-layer competitor renderers; four incident cases; local challenge harness; versioned file, CLI, trace, grant, and audit contracts; migration from real 0.3.2; results page with evidence and limitations.

**Explicitly not V1:** HTTP-serving proxy, OTel spans, GitHub Action for consumers, AuthZEN, Cedar/agentgateway integrations, full enterprise gateway, new database cluster, hosted red-team site, general CX monitoring, paid model APIs. Those belong to v1.1/v1.2 or later, per binding spec.

**Public honesty:** no outside audit; no users yet; owner-run red-team is not independent; name the product in public copy as “the agent authorization platform.” The core package, CLI, and URLs remain unchanged.

## 2. Hard safety, budget, and branch rules

1. All edits and commits go only to `release/v1/B12-atp-1.0`. Never force push. Never modify `main`, merge, create/open PRs, create tags (including annotation tag), publish to PyPI, or spend money.
2. `bench/annotations/*.yaml` **must never be edited**. The owner alone checks annotations and creates `bench-annotations-v1`.
3. No fabricated or estimated runs, scores, CI status, vulnerability claims, or test counts. Never disable, delete, suppress, skip, or xfail tests to get green. Read counts from JUnit XML. Existing documented skips must be named and accounted for.
4. Any environment-inaccessible tool or unavailable Linux binary is **ENV_BLOCKED** with exact error text. An incomplete or unrun test is **NOT_MEASURED**. A failed incident is a genuine **FAIL**; never edit its input to manufacture a pass.
5. Competitor policies derive from **the same preregistered task annotation** ATP receives, before injection. Render the strongest constraint each competitor supports, not an artificially weakened policy. Any dropped constraint records `source`, reason, and a competitor documentation URL.
6. Every discretionary architectural/semantics decision must be appended to the SDD ledger as `Ruling: <decision> — <why> — <cost if wrong>`.
7. Use the exact task commit subject from the binding plan, then `Co-Authored-By: ChatGPT GPT-6 <noreply@openai.com>` if this assistant authored the change. Separately committed verification infrastructure may use descriptive `ci:` subjects; document why.

## 3. Already accomplished versus actually measured

**Previously reviewed/done:** A3; B1-B2; C1-C10; D1. C8 added macOS CI but that leg remained NOT_MEASURED when the handoff was written. The handoff recorded 713 root tests (one skip) and 201 bench passes as *historical*, not present execution evidence.

**D2:** agentgateway source + historical binary evidence showed that `json(request.body).params.arguments` can authorize tool arguments even though the documented `mcp.tool.arguments` is empty. The 2026-11-05 D2 candidate updates finite numeric comparisons, resource-ID grammar, Unicode representation/length and documentation. Real-binary and full-suite verification remains **NOT_MEASURED** until a run executes. Tests that cannot obtain the binary must never silently PASS. A release-branch GitHub workflow was added for that purpose.

**Do not declare D2 done on the basis of GitHub commits, formatted source, prior binary experiments, or CI check appearance alone.**

## 4. Critical path, one task at a time

### D2 — verify/fix agentgateway (P0)

**Implement/test contracts:** `bench/src/atp_bench/layers/agentgateway_layer.py`, `bench/tests/test_agentgateway_layer.py`, `bench/competitors/agentgateway.md`. Assess the pending patch and verify:
- finite comparisons reject `-inf`, `inf` and NaN while preserving accepted numeric strings where feasible;
- resource IDs: 1–255 code points, nonempty, no `*`, no C0/DEL controls, across wildcard, typed wildcard, exact, and prefix scope;
- string lengths count code points as ATP does, or are identified as an approximation with examples;
- unicode string literals, including non-BMP values, round-trip to CEL correctly;
- duplicate JSON keys and batch-request handling, documented based on actual v1.6.0 evidence;
- large integer/float precision and out-of-range numeric string approximations explicitly documented;
- deny classifications are backed by an upstream journal, so gateway/client failures aren't mislabeled as blocked attacks.

**Mandatory verification:** Linux x86_64 pinned binary verified by `bench/data/tool_pins.yaml` SHA256; `bench/tests/test_agentgateway_layer.py`, root suite, full bench suite; ruff, mypy, four demos and relevant contract checks. Document exact commands, commit, JUnit counts, tool version, policy drops, and binary logs. Independent review must approve before claiming completion.

**Ruling template:** `Ruling: agentgateway raw-body CEL is considered for v1.6.0 comparison — the pinned HTTP handler exposes arguments and must receive the strongest policy — cost if wrong: invalid comparative results if upstream parsing or CEL semantics differ.`

**Gate:** do not proceed to D3 while required binary verification is ENV_BLOCKED or FAIL.

### D3 — ToolHive/Cedar

Use pinned ToolHive v0.55.2 only. Examine actual Cedar context semantics and what tool arguments are exposed *before* coding: tool name, scalar types, lists, string lengths, resource-prefix matching, and denial behavior. Write failing tests for name allowlist, scalar min/max, list subset reporting, wildcard/prefix handling, and binary end-to-end or exact ENV_BLOCKED. Confirm and document whether the remote HTTP MCP proxy requires a Docker/container runtime. Record all dropped constraints with versioned doc URLs. Commit the exact plan's D3 subject.

### D4 — Docker MCP Gateway and reference name-only layer

Build a small name-only **reference**, clearly not an existing competitor. Run Tool/Scope negative tests. For Docker MCP Gateway use the strongest built-in no-code policy; check `docker info`. If no daemon, record **ENV_BLOCKED with stderr**, not DENIED or an invented benchmark number. Verify whether argument restrictions are possible through native gateway configuration rather than assuming they aren't. Keep tests separate from dependency availability.

### E1 — tool-definition pinning and incident runner

Write tests first for initialization pinning and tool-definition changes. Add optional `ToolMapping.schema_sha256` over canonical upstream `tools/list` definition (name, description, inputSchema); fail closed when changed and deny with `TOOL_DEFINITION_CHANGED`. Handle change notifications, session-start revalidation, old unpinned configs, and golden format changes explicitly. Regenerate compatibility fixtures using `scripts/gen_compat.py` and record why the frozen-surface candidate changed *before* H1. Build a local incident runner with typed status and journal evidence.

### E2 — four public incident classes

Reconstruct **MCPoison** (definition swap), **PR-title/issue-text hijack**, **tool-description poisoning**, and **under-limit payment redirect**, each with a public source URL and synthetic locally executable fixture. Assert real upstream journal state under name-only vs ATP; pin each as an `atp test` regression. Never use real secrets or make live unauthorized external requests. **If ATP fails, commit the FAIL and stop for a ruling; do not edit the scenario to win.**

### F1 — live-runner implementation (no owner live sweep)

Build an interface for Claude Code and Codex plus a fully deterministic fake-agent executable. Validate: run-count planning, isolated MCP-only tools, no filesystem/shell tools, scrubbed transcripts, genuine AgentDojo utility/security evaluation, cached runs/resume, usage-limit `INCONCLUSIVE`, and graceful recovery. Verify actual `codex exec --help` options if CLI is installed; do not invent flags. Do not consume subscription quota or launch F2 without owner approval. If the plan's F1 smoke cannot run, record NOT_MEASURED with the exact missing prerequisites.

### G1 — local adversarial challenge

Implement the payments-style challenge: $100 limit, permitted on-file vendors only, forbidden recipient `acct-forbidden-0001`. Denied attempts do not reach the upstream payment ledger. Allowed actions do. Export all verifiable traces/evidence in JSONL, count by reason and attempts, and distinguish an actual forbidden ledger entry from a superficial error message. Publish scope rules and limitations; no internet-facing target needed.

## 5. OWNER GATE A1 — stop

Before any sweep or `bench-annotations-v1` tag:
1. Present the annotation files, utility amendments, exact relevant task counts, compatibility questions, and any found annotation defects (do not change annotations).
2. The **owner** reviews and creates the annotation pre-registration tag.
3. Only after owner confirmation proceed with A1 replay, A2 benchmark CI, and D5 competitor sweep. Never backfill or retune annotations based on injection outcomes.

## 6. After A1: A2 and D5

- **A1:** run ATP and open-layer utility and attack replays against all four suites (workspace, travel, banking, slack); publish raw JSONL and per-suite summary with denominators.
- **A2:** CI reruns the documented small reproducible slice and fails on any unexpected drift. Never re-annotate to get a pass.
- **D5:** run all six layers (open, name-only reference, ATP, agentgateway, ToolHive, Docker MCP Gateway) under identical preregistered annotations. Record ENV_BLOCKED per layer when inaccessible. Add competitor policy justifications and dropped-constraint inventory. Every published number references a committed raw output and pinned environment.

## 7. OWNER GATE F2 — stop

Print a detailed live-run plan *before* consuming quota: agents, models/CLI versions, layers, suites, total number of planned calls, storage volume and resume behavior. Ask which agents the owner approves. An owner subscription is not blanket permission to run a long sweep. An interrupted run is INCONCLUSIVE, not an inferred model failure or security success.

## 8. H1 → H2 → H3 release candidate

- **H1:** regenerate compatibility goldens twice and compare byte-for-byte; freeze versioned envelope, traces, policy, regression suite, CLI and exit-code contract. Document upgrade and backward-compatibility policy.
- **H2:** publish a *draft* `docs/results/v1.md` only from committed raw results. If A1 or D5 is owner-gated, placeholders show NOT_MEASURED, not estimates. Implement and run an internal link/reference checker. Separate model-free replay from the optional live-agent track. Always state “not independently audited” and “no users yet.”
- **H3 Step 1-2:** bump all `pyproject.toml` versions in lockstep; complete changelog, migration/known-limit docs and launch notes; run complete root, compat, upgrade, evals, full bench, all demos, packaging, twine, pip-audit/SBOM and 11-step release gate. Record `docs/release-v1/TEST_EVIDENCE.md` with exact commands and status. Commit only a release **candidate**, not a tag.
- **H3 Step 3-5 owner gates:** no PRs, no merge, no tags and no PyPI publication without explicit approval.

## 9. Standard verification matrix

| Gate | Evidence expected | Failure policy |
|---|---|---|
| Branch integrity | full branch name, SHA before and after, fast-forward commits | stop on unexpected head/merge |
| Quality | `ruff check`, `ruff format --check`, `mypy` logs | FAIL until fixed |
| Root | JUnit `tests/failures/errors/skipped` and skip inventory | no silent skip |
| Bench | JUnit `tests/failures/errors/skipped`; slow test present | no approximate count |
| D2 competitor | pinned binary SHA, version, CEL config, per-call journal, JUnit | ENV_BLOCKED if unavailable |
| Contract | `tests/compat`, `tests/upgrade`, deterministic generated goldens | FAIL blocks freeze |
| Demonstrations | wrap, injection, regression, MCP + evidence | NOT_MEASURED until run |
| Security | no unexpected grant, no missing decision, truthful incident statuses | FAIL blocks release |
| Package | built wheel, isolated install, `twine check`, dependency audit, SBOM | block release on failure |
| Documentation | source URLs, link check, per-claim raw result | do not publish unsupported numbers |

**Linux baseline commands:**

```bash
uv sync --all-packages
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest -q -p no:cacheprovider --junitxml=/tmp/root.xml
(cd bench && uv sync && uv run --no-sync pytest -q -p no:cacheprovider --junitxml=/tmp/bench.xml)
```

Store failures and output logs; do not alter test selection to obtain a flattering summary. CI execution on a branch is useful but must be checked by viewing the actual job and artifacts, not assumed from committing workflow YAML.

## 10. Delegation of engineering tasks

The release director may assign independent, narrowly scoped reviews on isolated branches/worktrees, but integration is serialized into B12 in task order. One writer per file; avoid concurrent writes to shared `docs/superpowers/handoff/2026-11-05-sdd-ledger.md`. Reviewers challenge invariants and verify binary outcomes, not simply summarize patches. A review must identify exact files and reproduce any reported failure.

## 11. Current blocker checklist and resumption protocol

Before any additional implementation:
- [ ] Confirm current B12 HEAD, no unexpected branch advance, and no main modifications.
- [ ] Locate the branch-only D2 GitHub Actions job, confirm whether it actually ran, and inspect logs plus JUnit artifact; **absence of status is NOT_MEASURED**.
- [ ] If D2 workflow fails or doesn't trigger, fix workflow without weakening assertions, push only B12 and inspect next run.
- [ ] If D2 binary tests fail, reproduce on pinned binary, fix code and adjust tests only to correct mistaken expected semantics.
- [ ] Review D2 fairness and accuracy, append rulings, then proceed to D3.
- [ ] Stop at A1 annotation review. Do not run owner-gated sweeps or touch tags.

**Status reporting on each session:** current SHA; task; changed files; commit links; exact JUnit counts; evidence URLs; PASS/FAIL/ENV_BLOCKED/NOT_MEASURED outcomes; documented rulings; next binding step and owner approvals required.

**No deadline can override an unmet security or honesty gate.**
