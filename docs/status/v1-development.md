# V1 development snapshot — not a published release

**Latest code:** [`release/v1/B12-atp-1.0`](https://github.com/TimelessVisions/agent-trust-plane/tree/release/v1/B12-atp-1.0)  
**Latest PyPI/GitHub release:** [`v0.3.2`](https://github.com/TimelessVisions/agent-trust-plane/releases/tag/v0.3.2)  
**Package version on this development branch:** `0.3.2` (the `1.0.0` bump is a later, gated step)  
**Development status:** Experimental, no users yet, not independently audited, not production-certified.

The product's working name is **ApexTrust Guard**. The repository, Python distribution and `atp` CLI retain their existing names. This page describes a *source-development snapshot*, not a new release.

## Reproducible security and test evidence

At commit [`ceda53d0`](https://github.com/TimelessVisions/agent-trust-plane/commit/ceda53d0bb231c39db479c940fd6247c70fe6594), all six release-branch [GitHub Actions jobs #42421031014](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/42421031014) completed successfully on November 7, 2026.

| Measured check | Actual result |
|---|---|
| Root pytest, Ruff, mypy and four demos | **PASS:** 733 collected, 732 passed, 1 explicitly documented optional third-party skip |
| Full AgentDojo benchmark **tests** | **PASS:** 226 tests; 0 failures, errors or skips |
| Synthetic incident harness and payment acceptance | **PASS:** 11 tests; 0 failures, errors or skips |
| Pinned agentgateway v1.6.0 executable | **PASS:** 9 tests |
| Pinned ToolHive v0.55.2 executable | **PASS:** 8 tests |
| Name-only negative controls and Docker-runtime failure classification | **PASS:** 3 tests; real Docker MCP Gateway behavior remains **NOT_MEASURED** |

The payment acceptance test now proves both sides of the boundary: a synthetic $480 USD payment to the trusted vendor account is forwarded, while a $640 USD attempt to an unapproved account is denied without an upstream execution. The fixture supplies an explicit $1,000 USD maximum and USD allowlist. No real funds or private credentials were used. **The original scripted calls, expected outcomes, and payments-v2 policy were not changed to get a green result.** The earlier failing CI remains in the Git history as evidence of the bug.

These are **test counts, not published benchmark attack-success rates**. Live-agent subscription sweeps and the Docker MCP Gateway product comparison have not been measured. This is not an independent audit.

## Remaining 1.0 release gates

1. **F1 and G1:** complete and verify the planned live-agent runner (without spending subscription quota) and the local red-team challenge with its evidence exporter. A real CLI smoke test can be `NOT_MEASURED` if no supported logged-in CLI is available.
2. **A1 OWNER GATE:** owner reviews all 97 pre-injection task annotations and their utility-change audit. Only the owner may create the `bench-annotations-v1` preregistration tag. See [annotation review](../../bench/annotations/OWNER_REVIEW.md). Some development/security tests predate the tag; disclose that chronology rather than claiming no earlier tests.
3. **A2 / D5:** after that tag, run a full, version-pinned competitor sweep; report harmful-action reach and legitimate utility from raw results. Real Docker MCP Gateway may remain `ENV_BLOCKED`/`NOT_MEASURED` if it cannot run; never substitute the name-only reference for Docker.
4. **F2 OWNER GATE:** obtain explicit approval before using the owner's Claude Code or Codex subscriptions for live-agent sweeps.
5. **H1–H3:** run the deterministic compatibility freeze, write the evidence-backed results page, set all distribution versions to 1.0.0 in lockstep, complete the 11-step release audit, and verify full multi-platform CI, packaging, advisories, SBOM and isolated-wheel install.
6. **H3 OWNER GATES:** open PRs (B11 first, then B12), merge, create a `v1.0.0` tag, and publish to PyPI only with specific owner approval.

We enabled the **normal cross-platform and packaging CI workflow on branch pushes** to gather preflight evidence without creating or merging a PR. This does not change tag rules or publishing permissions. See [release-gate tracker](../release-v1/RELEASE_GATES.md).

## Try the latest source with a safe local demo

```bash
git clone --branch release/v1/B12-atp-1.0 --single-branch https://github.com/TimelessVisions/agent-trust-plane.git
cd agent-trust-plane
uv run atp demo wrap
```

Requires Python 3.12+ and `uv`; uses a local synthetic MCP server. Do **not** connect this candidate to live payment services or customer-critical production tools. The enforcement path must be mediated by the proxy; an agent with direct upstream access can bypass it.

Please report actual vulnerabilities using [SECURITY.md](../../SECURITY.md), rather than posting secrets publicly. Other technical feedback is welcome through the [issue tracker](https://github.com/TimelessVisions/agent-trust-plane/issues).
