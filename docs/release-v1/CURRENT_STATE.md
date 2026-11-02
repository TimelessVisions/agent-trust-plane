# Current state — the agent authorization platform

Track B of the Timeless Visions V1 program. The repository, package, and CLI
names are unchanged (`agent-trust-plane`, `atp`). This document is a
measurement, not a release announcement.

## Git

| Item | Value |
|---|---|
| Repository | https://github.com/TimelessVisions/agent-trust-plane (public) |
| Default branch | `main` |
| `main` SHA (re-verified after `git fetch origin`) | `a418acfb3ba75c24565ea9d2c8492e754787fbb7` |
| `main` commit time | 2026-09-17 17:51:41 -0400 (`2026-09-17T21:51:41Z`) |
| `main` subject | Docs: v0.3.2 verification record uses the hashes of the tag build |
| Package version | `0.3.2` (not bumped) |
| This work branch | `release/v1/B1-mcp-deny-before-upstream` (from that SHA) |
| Measured on | 2026-10-29, Linux cloud VM, Python 3.12.3, uv 0.13.6 |

`origin/main` matched `a418acfb3ba75c24565ea9d2c8492e754787fbb7` after fetch.
The pushes on 2026-10-29 were to the alert branches below, not to `main`.

## Branches and open pull requests

Not merged, and not used as the base of this branch.

| Ref | Tip | Open PR |
|---|---|---|
| `main` | `a418acf` | — |
| `feat/photon-denial-alerts` | `0489cbf` (2026-10-29) | Draft PR #1, base `main`: “Add read-only Photon iMessage alerts for verified ATP denials” — https://github.com/TimelessVisions/agent-trust-plane/pull/1 |
| `feat/telegram-denial-alerts` | `870f43d` (2026-10-29) | Draft PR #3, base `feat/photon-denial-alerts` (stacked on #1): “ATP × Photon v0.2: Telegram direct-message denial alerts” — https://github.com/TimelessVisions/agent-trust-plane/pull/3 |

PR #1’s description says a real iPhone received a Photon iMessage for one
denial on 2026-10-28. That statement was not re-run here. A provider
accepting an alert is not device delivery. Neither PR is part of this
security proof.

Open issues, also untouched:

- #2 Security: upgrade locked dependencies flagged by pip-audit (2026-10-28)
- #4 Security: audit Spectrum SDK transitive npm dependencies before production (2026-10-29). The Spectrum bridge exists only on the Photon branch.

## Branch protection

The branch-protection API returned HTTP 403 (`Resource not accessible by
integration`). It was not changed. One repository ruleset is active:
“Protect release tags” (id 23830823, target `tag`, created 2026-09-22).
No tag was created. The owner’s instruction for this run is that branch
protection is off; this token could not confirm that independently.

`gh repo view` reported every classic permission flag false. `git fetch`
and `gh pr list` succeeded. Push permission is only known once this branch
is pushed.

## What is in the tree at `a418acf`

- Python workspace, `requires-python >= 3.12`, version `0.3.2`.
- Lockfile `uv.lock` pins `mcp` 2.2.0 (`mcp-2.2.0-py3-none-any.whl`,
  sha256 `bde982589473a060ae145e3406e9a5333fe538c97229ba841f5a7f92be004f81`,
  uploaded 2026-09-07). Requirement range is `mcp>=2.2,<3`.
- `httpx2` 2.13.0 is a real dependency of that SDK. `import httpx2` in the
  proxy is not a typo.
- CI: `.github/workflows/ci.yml` on push to `main` and on pull_request.
  Backend matrix: `ubuntu-latest` Python 3.12 and 3.13, plus
  `windows-latest` Python 3.13. `permissions: contents: read`. Actions are
  SHA-pinned. Jobs: `backend`, `package` (wheel, isolated `uvx`, pip-audit,
  SBOM), `dashboard` (Node 22, `npm ci`, typecheck, build).
- `publish.yml` runs only on a published GitHub Release or manual dispatch.
  It was not run.
- Compatibility claims live in `docs/integrations/compatibility.md`
  (maintainer matrix dated 2026-09-17). Several cells say VERIFIED for
  stdio, Streamable HTTP upstream, and protocol `2025-11-25`. Streamable
  HTTP served by the proxy is NOT SUPPORTED. `2026-07-28` is not claimed
  there.
- Test command used by CI and `scripts/check.sh`: `uv run pytest -p no:warnings`.
- Historical docs say “439 tests”. That number does not match a fresh
  count. See `TEST_EVIDENCE.md`.

## Baseline before this branch’s code change

Commands and counts are in `TEST_EVIDENCE.md`. Short version, all on
`a418acf`, Python 3.12.3, 2026-10-29:

- `uv run pytest -p no:warnings`: **439 passed, 1 skipped**, exit 0
  (440 collected). The skip is the opt-in third-party server test.
- ruff, ruff format (190 files), mypy (76 files): pass.
- `python -m atp_evals`: 8/8 pass.
- demos `injection`, `regression`, `mcp`, `wrap`: exit 0.
- sample regression suite: 8/8 under `payments-v2`; `payments-v1` exits 1
  as the workflow requires; policy impact reports 2 narrowed.
- `scripts/check_links.py`: 73 files, 0 broken relative links.
- Dashboard `npm ci`, typecheck, and production build: completed (Next.js
  15.5.25, Node v22.23.4).
- `pip-audit --disable-pip --no-deps --strict` on the locked runtime set:
  **exit 1**, five findings in three packages. Details in `BLOCKERS.md`.

Python 3.13, 3.14, Windows, and macOS were not executed on this VM.

## False-green paths found in the baseline

1. **Delete “never reached upstream” was inferred from a file that still
   existed** (`adapters/mcp/tests/test_proxy_e2e.py`,
   `packages/cli/tests/test_wrap_e2e.py`, and `atp demo mcp`). The notes
   server’s `delete_note` unlinks the file, so a surviving file means that
   unlink did not finish. It does not record whether the tool function was
   entered. The new journal test is the receipt proof.
2. **Every MCP trace said `protocol unknown`.** The proxy read
   `protocolVersion` off the SDK result object. The field is
   `protocol_version`. The compatibility matrix still said the negotiated
   revision was verified as `2025-11-25`. The handshake version is real;
   the trace was not recording it. Fixed on this branch.
3. **`pytest -p no:warnings` disables pytest’s warnings plugin**, so
   `filterwarnings = error::DeprecationWarning:atp_.*` in `pyproject.toml`
   does not apply to CI or `scripts/check.sh`. A full run with the plugin
   enabled still exited 0. The only warning was Starlette’s
   `anyio.abc.BlockingPortal` deprecation, which the filter does not
   cover. The CI command would not fail an `atp_*` deprecation today.
4. **The third-party MCP test is skipped unless `ATP_E2E_NPX=1`.** CI does
   not set that variable. The job is green anyway. A green backend job is
   not verification of `@modelcontextprotocol/server-filesystem`.
5. **`docs/release/verification.md` contradicts itself** on the same day:
   “438 passed, 1 skipped; 439 collected” and later “439 passed, 1
   skipped”. This VM’s baseline is 439 passed, 1 skipped, 440 collected.
6. **Skipped pytest tests do not fail the process.** One intentional skip
   is enough for a green job. GitHub would also report a skipped *job* as
   success; this workflow does not conditionally skip jobs.
7. **`atp doctor --port 1` checks that port 1 is free.** It does not prove
   a gateway is listening.

Shadow mode still forwards a denial on purpose. That is labeled
`WOULD_DENY` in the existing wrap test. It is not a false green if the
mode is read. It is a bypass if an operator thinks shadow mode enforces.

## After the proof change

Same VM, still version `0.3.2`. `uv run pytest -p no:warnings` finished
2026-10-29T15:32:36Z: **445 passed, 1 skipped in 36.10s**, exit 0.
`--collect-only -q` sums to 446 tests. The six new tests are in
`adapters/mcp/tests/test_deny_before_upstream.py`. ruff (192 files
formatted) and mypy (76 files) passed after the edit. On commit
`c65ead064e5aa15158c307b8a5daac1ee90d922b`, at 2026-10-29T15:35:53Z,
`python -m atp_evals` was 8/8 and the accounts-payable regression suite
exited 0. Demos, the dashboard, and the package job were not re-run
on this VM after the patch. GitHub Actions run
[40903300097](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/40903300097)
on `cfb325d224c438d24f4169039fffd0d9dbd2e47c`: three backend jobs and the
dashboard passed; the package job failed at `pip-audit` (blocker B1).
