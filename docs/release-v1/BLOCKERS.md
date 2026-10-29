# Blockers — the agent authorization platform

Updated 2026-10-29 on `release/v1/B2-supply-chain-and-false-green`.
The B1 rows below are the state after that branch’s lockfile pin.
Earlier evidence is in `TEST_EVIDENCE.md` and `REUSE_DECISIONS.md`.
Severity is for a developer-use release of this repository, not for a
claim of universal enforcement or an audited certification.

## P0

No open P0 on the deny-before-receipt path after this branch.

One truthfulness defect was found and fixed here, and is not still open:
MCP traces recorded `protocol unknown` because
`adapters/mcp/src/atp_adapter_mcp/proxy.py` read the attribute
`protocolVersion`. The SDK field is `protocol_version`. Handshake clients
were already negotiating `2025-11-25`. The trace now records that string.
The failing assertion was
`test_allowed_write_is_forwarded_and_delete_is_not_received` (stdio and
HTTP) and `test_removing_the_deny_rule_fails_the_regression_check`, all
three failing only on the provenance string, then passing after the field
fix.

## P1

| ID | Blocker | Evidence | Needed before a release tag |
|---|---|---|---|
| B1 | Lockfile bump is in this draft and is not merged. | Before, 2026-10-29T15:44:19Z: five findings, `pip-audit` exit 1 (`certifi==2026.7.22`, `opentelemetry-api==1.44.0`, `pyjwt==2.14.0`). After, 2026-10-29T15:47:41Z: `pip-audit --disable-pip --no-deps --strict` exit 0, “No known vulnerabilities found”, pins `certifi==2026.10.19`, `opentelemetry-api==1.45.1`, `pyjwt==2.15.0`. Reachability is in `REUSE_DECISIONS.md`. | Director approval to merge the lockfile. No other dependency was moved. |
| B2 | No independent reviewer has re-run this proof from the PR SHA. | This branch’s tests were written and run by the same worker. | A different worker, clean checkout, the commands in `TEST_EVIDENCE.md`. |
| B3 | A client that can start or reach the upstream MCP server bypasses the proxy. Startup cannot see that second path. | `test_direct_upstream_access_is_not_protected`. `SECURITY_AND_LIMITS.md`. The proxy now refuses to copy gateway credentials into the upstream, and warns on a non-loopback URL. It does not refuse remote HTTPS, and it does not search the host for another copy of the server. | Keep the developer-use scope. Do not describe the proxy as universal protection. |
| B4 | `2026-07-28` is not a supported product revision. | `SCOPE.md`. A modern stdio client can complete `tools/call` and the delete was still not journaled. The rest of that revision was not implemented or measured. | Do not document or demo it as supported. |
| B5 | Python 3.14 and macOS are still unmeasured. The PR CI matrix did run. | Actions run [40903300097](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/40903300097) on `cfb325d`. Backend jobs passed: ubuntu 3.12, ubuntu 3.13, windows 3.13 (each includes pytest, evals, demos, the sample suite). Dashboard passed. **Package failed** in `uvx pip-audit` (B1). SBOM did not run because that step failed first. The numeric “445 passed” count is from the local 3.12 run, not copied out of the CI log. | Keep 3.14 and macOS out of the supported list. Do not treat the red package job as a test failure. |

## P2

| ID | Item | Evidence |
|---|---|---|
| C1 | Addressed on this branch, not yet merged. CI pytest no longer passes `-p no:warnings`, so `filterwarnings = error::DeprecationWarning:atp_*` applies. `scripts/check.sh` and `scripts/check.ps1` match it. | `.github/workflows/ci.yml`. A plugin-on run still reports Starlette’s `anyio.abc.BlockingPortal` deprecation, which the filter does not treat as an error. |
| C2 | Addressed on this branch, not yet merged. A dedicated job is named `NOT_MEASURED third-party MCP filesystem server`. It writes that string to the step summary and a warning annotation. It does not install the npm server. A GitHub “skipped job” was not used, because GitHub reports skipped jobs as success. | `.github/workflows/ci.yml` job `third-party-mcp`. The backend pytest skip remains; the new job is what makes the gap visible. |
| C3 | Older docs say “439 tests” and `docs/release/verification.md` gives two different passed counts. | Baseline here: 440 collected, 439 passed, 1 skipped. After this branch: 446 collected, 445 passed, 1 skipped. |
| C4 | Photon iMessage (PR #1) and Telegram (PR #3) are draft, stacked, and out of this release. Issue #4 asks for an npm audit of the Spectrum SDK before any production use. | PR list 2026-10-29. Not merged, not built on. |
| C5 | `input_required` / task results are refused in code after the upstream call returns. A tool that already performed a side effect and then returned `input_required` would have run. | `TrustPlaneProxy._complete_or_refuse` in `proxy.py`. Not exercised with a live `input_required` result in this run. |
| C6 | The proxy does not serve Streamable HTTP. Legacy HTTP+SSE is not supported. | `serve()` uses `stdio_server()` only. Compatibility matrix already says NOT SUPPORTED. |
| C7 | Default `uvx pip-audit` on this VM failed before auditing because `python3.12-venv` / ensurepip is missing. Exit status of that invocation was not captured (it was in a pipeline). | The conclusive command is the `--disable-pip --no-deps` run in B1. |
| C8 | Branch-protection state was not readable (HTTP 403). A tag ruleset is active. Neither was modified. | `CURRENT_STATE.md`. |

## Explicitly not a blocker for this draft

The flagship allow / deny / explain / regression sequence passed on this VM
for the transports and revisions in `SCOPE.md`. That does not clear B1–B5.
