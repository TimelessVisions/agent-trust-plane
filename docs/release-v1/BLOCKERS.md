# Blockers — the agent authorization platform

Updated 2026-10-29T15:32:36Z from the measurements in `TEST_EVIDENCE.md`.
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
| B1 | Locked runtime dependencies have known advisories. Not upgraded here (version and lockfile left at 0.3.2). | `pip-audit` 2.10.1, `--disable-pip --no-deps --strict`, exit 1, 2026-10-29T15:25:15Z. `certifi==2026.7.22` PYSEC-2026-4320 (fix 2026.10.19; advisory describes a compromised emSign intermediate and an on-path TLS risk; a third-party page labels CVSS 9.1). `opentelemetry-api==1.44.0` CVE-2026-114603 (GitHub: moderate; unbounded `tracestate` parse; fix 1.45.1). `PyJWT==2.14.0` PYSEC-2026-4141 (OSV CVSS 5.3) and PYSEC-2026-4183. Issue #2 already tracked the certifi and OpenTelemetry findings from CI. This run also reports PyJWT. | Owner approval to bump the lockfile. No advisory was exploit-tested in this repo. “Listed by pip-audit” is not a proof of exploitability against `atp`. |
| B2 | No independent reviewer has re-run this proof from the PR SHA. | This branch’s tests were written and run by the same worker. | A different worker, clean checkout, the commands in `TEST_EVIDENCE.md`. |
| B3 | A client that can start or reach the upstream MCP server bypasses the proxy. | Existing `test_direct_upstream_access_is_not_protected`. `docs/security/enforcing-the-boundary.md`. | Keep this inside the developer-use scope. Do not describe the proxy as universal protection. |
| B4 | `2026-07-28` is not a supported product revision. | `SCOPE.md`. A modern stdio client can complete `tools/call` and the delete was still not journaled. The rest of that revision was not implemented or measured. | Do not document or demo it as supported. |
| B5 | Python 3.14 and macOS are still unmeasured. The PR CI matrix did run. | Actions run [40903300097](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/40903300097) on `cfb325d`. Backend jobs passed: ubuntu 3.12, ubuntu 3.13, windows 3.13 (each includes pytest, evals, demos, the sample suite). Dashboard passed. **Package failed** in `uvx pip-audit` (B1). SBOM did not run because that step failed first. The numeric “445 passed” count is from the local 3.12 run, not copied out of the CI log. | Keep 3.14 and macOS out of the supported list. Do not treat the red package job as a test failure. |

## P2

| ID | Item | Evidence |
|---|---|---|
| C1 | CI pytest disables the warnings plugin (`-p no:warnings`), so the `atp_*` DeprecationWarning filter never runs in CI. | `pyproject.toml` `filterwarnings`; `.github/workflows/ci.yml`. A plugin-on run on this branch exited 0. The warning observed was in Starlette, not `atp_*`. |
| C2 | `@modelcontextprotocol/server-filesystem` stays skipped in CI. | `adapters/mcp/tests/test_proxy_third_party.py` skips unless `ATP_E2E_NPX=1`. This VM did not set it. The job is still green. |
| C3 | Older docs say “439 tests” and `docs/release/verification.md` gives two different passed counts. | Baseline here: 440 collected, 439 passed, 1 skipped. After this branch: 446 collected, 445 passed, 1 skipped. |
| C4 | Photon iMessage (PR #1) and Telegram (PR #3) are draft, stacked, and out of this release. Issue #4 asks for an npm audit of the Spectrum SDK before any production use. | PR list 2026-10-29. Not merged, not built on. |
| C5 | `input_required` / task results are refused in code after the upstream call returns. A tool that already performed a side effect and then returned `input_required` would have run. | `TrustPlaneProxy._complete_or_refuse` in `proxy.py`. Not exercised with a live `input_required` result in this run. |
| C6 | The proxy does not serve Streamable HTTP. Legacy HTTP+SSE is not supported. | `serve()` uses `stdio_server()` only. Compatibility matrix already says NOT SUPPORTED. |
| C7 | Default `uvx pip-audit` on this VM failed before auditing because `python3.12-venv` / ensurepip is missing. Exit status of that invocation was not captured (it was in a pipeline). | The conclusive command is the `--disable-pip --no-deps` run in B1. |
| C8 | Branch-protection state was not readable (HTTP 403). A tag ruleset is active. Neither was modified. | `CURRENT_STATE.md`. |

## Explicitly not a blocker for this draft

The flagship allow / deny / explain / regression sequence passed on this VM
for the transports and revisions in `SCOPE.md`. That does not clear B1–B5.
