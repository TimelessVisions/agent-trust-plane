# Version 1.0 — release gate tracker

**As of November 7, 2026.** Branch `release/v1/B12-atp-1.0`. This is a **go/no-go tracker**, not release approval. Nothing has been merged to `main`, tagged as 1.0, or published. The source distribution remains version 0.3.2.

| Gate | Status | Evidence or remaining action |
|---|---|---|
| E2: four local synthetic security incidents | **PASS** | 11/11 real local-fixture tests on [run #42421031014](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/42421031014). Separate companions passed. |
| E2: bounded legitimate/redirected payment | **PASS** | The original calls/expectations unchanged. $480 permitted; $640 wrong destination denied before upstream. Explicit $1,000 USD limit added only to synthetic config. |
| Root verification and demos | **PASS** | 733 JUnit cases; 732 passed, one opt-in third-party skip, no failures. Ruff, mypy and demos passed on the same run. |
| Full benchmark *unit/integration tests* | **PASS** | 226/226 JUnit tests passed. This is **not** a published harm/utility sweep. |
| D2 agentgateway / D3 ToolHive pinned binaries | **PASS** | 9/9 and 8/8 respectively in Linux CI. |
| D4 name-only reference | **PASS** | 3/3 reference and Docker-unavailable tests. Actual Docker MCP Gateway policy behavior is **NOT_MEASURED**. |
| F1 live-agent runner and safe smoke | **NOT_MEASURED** | Runner and fake-agent tests still to be implemented. CLI smoke depends on owner-supported login/environment. |
| G1 local red-team challenge and exporter | **NOT_MEASURED** | Harness and independent attempt-evidence verification still to be implemented. |
| A1 annotation review and preregistration | **OWNER GATE** | 97 current annotations, five documented utility-driven additions. No owner-approved `bench-annotations-v1` tag. |
| A2/D5: model-free public competitive rates | **NOT_MEASURED** | Must wait for A1 tag; provide raw file, versions, N/A and dropped-constraint disclosures. |
| F2 live-agent sweep | **OWNER GATE** | Do not spend a subscription or use paid APIs without explicit approval. |
| H1 format freeze and deterministic goldens | **NOT_MEASURED** | Candidate formats and compat tests exist; do not declare frozen while 1.0 contract may change. |
| H2 public results and links | **NOT_MEASURED** | Do not invent rates or market claims; publish placeholders until A2/D5 is measured. |
| H3 full release preflight | **NOT_MEASURED** | Normal cross-platform CI and packaging preflight are now triggered by release-branch pushes. Verify Windows/macOS, wheel, isolated install, audit, SBOM, docs and all 11 legacy gates. |
| H3 PRs, merge, `v1.0.0` tag, PyPI | **OWNER GATE** | Specific manual approval at each step, after all independent reviews and gates. |

**Important:** A green six-job Linux workflow is necessary but insufficient for 1.0. The added push trigger for `.github/workflows/ci.yml` checks other release surfaces and does not auto-publish or open PRs. Refer to the exact branch head and workflow SHA for new measurements, and never upgrade `NOT_MEASURED` to `PASS` from assumptions.

## Explicit owner actions remaining

After F1/G1, review the [annotation audit](../../bench/annotations/OWNER_REVIEW.md) and decide whether to approve the `bench-annotations-v1` tag. Later approve or decline F2 subscription usage. Only after release candidate CI and review pass, explicitly approve stacked PRs, merges, version tag and publication.

**Ruling:** continue strict preflight checks without creating PRs, tags or releases — the approval gates preserve traceability and prevent publication of a partially measured security claim — cost if wrong: project visibility remains on the development branch longer, but no unsafe security guarantee is represented as generally available.
