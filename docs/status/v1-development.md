# V1 development snapshot — not a release

**Branch:** [`release/v1/B12-atp-1.0`](https://github.com/TimelessVisions/agent-trust-plane/tree/release/v1/B12-atp-1.0)  
**Published release:** [`v0.3.2`](https://github.com/TimelessVisions/agent-trust-plane/releases/tag/v0.3.2)  
**Python package version in the development branch:** `0.3.2` until the later, owner-gated version bump  
**Review state:** Experimental; no users yet; no independent security audit; not ready for production payment actions.

The product's working name is **ApexTrust Guard**. The source repository, Python distribution and `atp` command retain their existing names. This page is for source reviewers and potential *staging-only* design partners; it is **not** a GA announcement.

## What is available on this branch

- Policy-based delegated authorization: bounded agent capabilities, resources, and action arguments, with deny-before-upstream enforcement on the mediated path.
- MCP wrapper and tool-definition pinning, including schema/description revalidation before pinned calls. [Design and limitations](../security/tool-pinning.md).
- Deterministic model-free AgentDojo replays, competitor renderers (agentgateway and ToolHive tested against their pinned binaries), synthetic name-only reference and an unverified Docker MCP Gateway adapter.
- Synthetic incident fixtures for a changed tool definition, tool-description poisoning, a PR-title redirection and an invoice payment redirection. These are **scripted calls**, not measurements of whether live AI models follow an injection.
- Local security regression and evidence workflow. [Full E2 record](../superpowers/handoff/2026-11-05-sdd-ledger.md).

## Release blockers and measured evidence

The latest six-job run available at the time of this snapshot was [GitHub Actions #42068445542](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/42068445542), on commit `2c67b82`.

| Gate | Measured status |
| --- | --- |
| Root suite, Ruff lint, format, mypy, four demos | **PASS** — 733 tests, 0 failures/errors, 1 documented optional skip |
| agentgateway v1.6.0 pinned binary | **PASS** |
| ToolHive v0.55.2 pinned binary | **PASS** |
| D4 name-only and Docker-unavailable checks | **PASS**; real Docker MCP Gateway comparison still **NOT_MEASURED** |
| E1/E2 targeted incident suite | **FAIL** — 11 tests, 1 failure; remaining 10 passed |
| Full AgentDojo benchmark test suite | **FAIL** — 226 tests, 1 failure; remaining 225 passed |

**Known failing scenario:** The real MCP proxy refuses both an unauthorized-destination synthetic payment **and** an intended legitimate payment. The existing incident fixture delegates `pay:vendor` without a required per-payment monetary maximum. The policy now fails closed on an unbounded payment; the fixture must be corrected through the documented owner decision to prove legitimate utility without loosening security. The incident's original calls and expected outcome must not be silently weakened.

**Stop points:** Independent security review, E2 owner ruling and corrected end-to-end evidence; annotation pre-registration owner gate; live-agent quota gate; final compatibility/packaging gate; explicit owner permission for PRs, merging to `main`, the `v1.0.0` tag and publication to PyPI. No successful v1.0.0 release is claimed.

## Try the safe local demonstration

```bash
git clone --branch release/v1/B12-atp-1.0 --single-branch https://github.com/TimelessVisions/agent-trust-plane.git
cd agent-trust-plane
uv run atp demo wrap
```

Requires Python 3.12+ and `uv`. The demo uses a local synthetic MCP server; it requires no production credentials or payment integration. Do **not** connect this development candidate to live funds or customer-critical tools.

## Feedback from technical reviewers

Constructive feedback is especially useful on the documented authorization boundary, schema-pin races, delegated monetary limits and synthetic incident reproducibility. Share reproducible findings through the repository's [issue tracker](https://github.com/TimelessVisions/agent-trust-plane/issues), and report actual vulnerabilities through [SECURITY.md](../../SECURITY.md) rather than posting secrets in public issues.

This document reflects measured evidence at its cited commit, not a claim that later commits or configurations passed the same gates.
