# Test evidence — the agent authorization platform

All times are UTC. The VM is Linux, CPython 3.12.3 (`/usr/bin/python3`),
uv 0.13.6, pytest 9.1.1, mcp 2.2.0, Node v22.23.4. No other Python was
installed. Commands were run from the repository root.

## Baseline, before application changes

Tree: `main` at `a418acfb3ba75c24565ea9d2c8492e754787fbb7`.
`uv sync` used that interpreter and installed the locked set, including
`mcp==2.2.0` and `httpx2==2.13.0`.

| UTC | Command | Result |
|---|---|---|
| 2026-10-29T15:21:02Z–15:21:29Z | `uv run pytest -p no:warnings -ra --tb=line` | Exit 0. **439 passed, 1 skipped in 26.25s.** Skip: `adapters/mcp/tests/test_proxy_third_party.py` (`ATP_E2E_NPX` unset). `--collect-only -q` file counts sum to 440. |
| 2026-10-29T15:21:39Z–15:21:57Z | `uv run ruff check .` | Exit 0. All checks passed. |
| same window | `uv run ruff format --check .` | Exit 0. 190 files already formatted. |
| same window | `uv run mypy` | Exit 0. No issues in 76 source files. |
| same window | `uv run python -m atp_evals` | Exit 0. 8/8 passed (EVAL-001 through EVAL-008). |
| same window | `uv run atp doctor --port 1` | Exit 0. Port 1 reported free. This does not open a server. |
| same window | `uv run atp demo injection` | Exit 0. DENY `PAYMENT_EXCEEDS_DELEGATED_AUTHORITY`, hash chain intact, ledger rows 0. |
| same window | `uv run atp demo regression --out /tmp/demo-regression.yaml` | Exit 0. payments-v1 0/1, payments-v2 1/1 on the generated case. |
| same window | `uv run atp demo mcp` | Exit 0. Write forwarded, delete `CAPABILITY_NOT_GRANTED`, file still present. The demo text says the delete never reached the upstream; the check is the surviving file, not a receipt log. |
| same window | `uv run atp demo wrap --out /tmp/wrap-demo` | Exit 0. Explain names `notes:destroy`. Regression case passes under `notes-v1`. |
| same window | `uv run atp test examples/regression-suite/accounts-payable.yaml --junit /tmp/regression.xml --json /tmp/regression.json` | Exit 0. 8/8 under `payments-v2`. |
| same window | `uv run atp test examples/regression-suite/accounts-payable.yaml --policy-set payments-v1 --quiet` | Exit 1, as the CI step requires. |
| same window | `uv run atp policy impact --from payments-v1 --to payments-v2 --suite examples/regression-suite/accounts-payable.yaml` | Exit 0. 8 actions: 0 widened, 2 narrowed, 6 unchanged. |
| same window | `uv run python scripts/check_links.py` | Exit 0. 73 files, 0 broken relative links. |
| 2026-10-29T15:24:27Z area | `uv run pytest -q --tb=line -ra` (warnings plugin left on) | Progress showed one skip and no `FAILED` line. The process exit code was not captured because the command was piped to `tail`. The captured warning is Starlette’s `anyio.abc.BlockingPortal` deprecation, not an `atp_*` warning. |
| 2026-10-29T15:24:50Z area | `cd apps/dashboard && npm ci && npm run typecheck && npm run build` | Completed. Next.js 15.5.25 production build. The shell recorded `DASH_EXIT:0` after a pipeline, so treat the build log, not that echo, as the evidence. |
| 2026-10-29T15:25:15Z | `/workspace/.venv/bin/pip-audit -r /tmp/req.txt --strict --disable-pip --no-deps` | **Exit 1.** Five findings, three packages. See `BLOCKERS.md` B1. `uv export --format requirements-txt --no-hashes --no-emit-project --no-dev -o /tmp/req.txt` produced the input. A default `pip-audit` without `--disable-pip` printed an ensurepip / `python3.12-venv` failure and produced no advisory table; that exit code was not captured. |

Not run in the baseline: `ATP_E2E_NPX=1`, `uv build`, the publish workflow,
Python 3.13/3.14, Windows, macOS, and a live GitHub Actions run of this SHA.
The last recorded full CI success in the repo docs is Actions run
35234834560 at commit `a4ac997` (2026-09-17), which is not this SHA.

## Proof tests, written first

File: `adapters/mcp/tests/test_deny_before_upstream.py`.
Sandbox: `adapters/mcp/tests/sandbox_journal_server.py`.

First run, before the protocol-field fix, 2026-10-29T15:27:53Z:

`uv run pytest adapters/mcp/tests/test_deny_before_upstream.py -p no:warnings --tb=short -ra`

**3 failed, 3 passed in 8.54s.** The failures were only:

```text
assert 'protocol 2025-11-25' in 'mcp tools/call via atp-proxy (stdio, protocol unknown)'
assert 'protocol 2025-11-25' in 'mcp tools/call via atp-proxy (http, protocol unknown)'
```

The journal assertions, the capability denial, and the policy-regression
failure had already passed in that run. The three passes were the SDK
constant pin and both modern-client parameter values. The fix is
`_negotiated_protocol` in `adapters/mcp/src/atp_adapter_mcp/proxy.py`.

What each test requires:

| Test | Transport / client | Assertion that matters |
|---|---|---|
| `test_allowed_write_is_forwarded_and_delete_is_not_received[stdio]` | `atp mcp wrap` over stdio, upstream sandbox subprocess, `ClientSession.initialize` | Client protocol `2025-11-25`. Write text `wrote todo (8 chars)` and file `todo.txt`. Delete `is_error`, `CAPABILITY_NOT_GRANTED`. Journal exactly `["write_note"]`. Trace integrity valid, no `execution_released` / `execution_attempted` / `execution_completed`. Provenance contains `protocol 2025-11-25` and `stdio`. `atp policy explain` contains `DENY  CAPABILITY_NOT_GRANTED` and `delegate capability 'notes:destroy'`. |
| same, `[http]` | Same wrap, upstream is the sandbox’s `streamable_http_app()` on `127.0.0.1` | Same, provenance contains `http`. |
| `test_removing_the_deny_rule_fails_the_regression_check` | stdio. Capability `notes:destroy` is delegated. Declared rule `never-delete` (`kind: deny`) on `mcp.notes` / `delete_note`. | Delete reason `ACTION_DENIED_BY_POLICY`. Journal exactly `["write_note"]`. Explain names `never-delete`. `atp regression add` then `atp test` exits 0. Replacing the rule with an empty rule list makes `atp test` exit 1, with `ALLOW` and `expected DENY` in the output. |
| `test_handshake_revision_constants_match_the_pinned_sdk` | none (imports the installed SDK) | `LATEST_HANDSHAKE_VERSION == "2025-11-25"`. `"2026-07-28"` is not in `HANDSHAKE_PROTOCOL_VERSIONS`. `MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)`. |
| `test_modern_client_cannot_deliver_a_denied_delete[auto]` and `[2026-07-28]` | stdio proxy, MCP `Client` | Both modes reported protocol `2026-07-28` (printed on the 2026-10-29 measurement run). Write is not an error. Delete is `CAPABILITY_NOT_GRANTED`. Journal exactly `["write_note"]`. The stored trace still says upstream `protocol 2025-11-25`. |

The journal line is appended and `fsync`’d inside the tool, before
`write_text` or `unlink`. Absence of `delete_note` means that function
did not start. This is a real MCP server (`MCPServer` from mcp 2.2.0),
not a mock of the proxy.

## Full suite after the fix

| UTC | Command | Result |
|---|---|---|
| 2026-10-29T15:30:13Z–15:30:51Z | `uv run ruff check .` | Exit 0. |
| same window | `uv run ruff format --check .` | Exit 0. 192 files already formatted. |
| same window | `uv run mypy` | Exit 0. 76 source files. |
| same window | `uv run pytest -p no:warnings -ra --tb=line -q` | Exit 0. The `-q` capture in that invocation did not include the final count line. |
| 2026-10-29T15:32:36Z (pytest reported 36.10s) | `uv run pytest -p no:warnings --tb=no -rf` | Exit 0. **445 passed, 1 skipped in 36.10s.** |
| 2026-10-29, just before that run | `uv run pytest --collect-only -q -p no:warnings` | Per-file counts sum to **446**. The new file contributes 6. |

Delta from the baseline: +6 passed, skip unchanged (439+6=445, 440+6=446).

Not re-run after the patch: evals, demos, dashboard, `uv build`,
pip-audit (the lockfile did not change), link check (run again after
these docs are committed if the script only sees tracked files),
Windows, macOS, Python 3.13, Python 3.14, `ATP_E2E_NPX=1`.

## What was not verified

- That a `2026-07-28` client speaks stateless HTTP to this proxy. The
  proxy does not serve HTTP.
- `server/discover` request bytes, `Mcp-Method` / `Mcp-Name` headers,
  MRTR `input_required` round trips, tasks, list cache hints, OAuth
  issuer checks, or CIMD.
- A `2026-07-28` upstream. The proxy’s upstream client always
  `initialize()`s.
- The third-party Node filesystem server.
- Photon or Telegram delivery.
- Whether the advisories in B1 are exploitable through `atp`.
- GitHub Actions on this branch (it had not been pushed when the suite
  was run).
- An independent re-run from a clean checkout by a different worker.
