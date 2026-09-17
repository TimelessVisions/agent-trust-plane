# v0.3.0 verification record (2026-09-17)

Environment: Windows 11 10.0.26200, Python 3.14.6 (uv-managed), uv 0.9,
Node 24.18 / npm, MCP Python SDK 2.2.0. All commands run from the
repository root at the release-candidate tree; results copied from the
terminal. Linux and Windows CI results are recorded in the GitHub Actions
section at the end; macOS is not in the matrix and was not run.

| # | Command | Result |
|---|---|---|
| 1 | `uv run ruff check .` | All checks passed |
| 2 | `uv run ruff format --check .` | 184 files already formatted |
| 3 | `uv run mypy` (strict) | Success: no issues found in 76 source files |
| 4 | `uv run pytest -p no:warnings` | **438 passed, 1 skipped** (opt-in npx test), 1 m 10 s; 439 collected |
| 5 | `ATP_E2E_NPX=1 uv run pytest adapters/mcp/tests/test_proxy_third_party.py` | 1 passed (reference filesystem server) |
| 6 | `uv run python -m atp_evals` | 8/8 passed |
| 7 | `uv run atp demo injection` / `regression` / `mcp` / `wrap` | exit 0 / 0 / 0 / 0 |
| 8 | `uv run atp test examples/regression-suite/accounts-payable.yaml --quiet` | exit 0 (8/8 under payments-v2) |
| 9 | same with `--policy-set payments-v1` | exit 1 (2 changed, as intended) |
| 10 | `uv run atp policy impact --from payments-v1 --to payments-v2 --suite …` | 8 recorded actions: 0 widened, 2 narrowed, 6 unchanged |
| 11 | `cd apps/dashboard && npm run typecheck && npm run build` | clean; static build OK |
| 12 | `uv build` | `agent_trust_plane-0.3.0-py3-none-any.whl`, `.tar.gz` |
| 13 | `uvx --isolated --from dist/agent_trust_plane-0.3.0-py3-none-any.whl atp doctor --port 1` | all ok |
| 14 | `uv tool install dist/…whl` → `atp demo wrap` from a directory outside the repo → `uv tool uninstall` | exit 0; the wheel is self-contained (`pipx` is not installed here; `uv tool` is the equivalent path) |
| 15 | `uvx --isolated --from git+file:///…/agent-trust-plane atp doctor` | ok (13.6 s) — the git-URL install path works |
| 16 | wheel metadata | Name `agent-trust-plane`, Version 0.3.0, MIT, `Requires-Python >=3.12`, 7 runtime deps, `console_scripts atp = atp_cli.main:main`, README embedded as long description (image link is relative; use an absolute raw URL when publishing to PyPI) |
| 17 | `uvx pip-audit -r <locked runtime set> --strict` | No known vulnerabilities found (42 components) |
| 18 | `uv run python scripts/sbom.py --out dist/sbom.cdx.json` | 42 components, CycloneDX 1.5 |
| 19 | `uv run python scripts/check_links.py` | 68 files, 0 broken relative links |
| 20 | CI YAML parse (ci.yml, example workflow, composite action) | ok; actions SHA-pinned; `permissions: contents: read` |
| 21 | secret scan (tracked tree, all history) | only the deliberate dummy token in `test_identity_security.py`; no keys; no `.env`/`.db`/`keys.env`/`.atp` tracked |
| 22 | private-path scan (tracked tree, history) | none |
| 23 | `uv run python benchmarks/authz_overhead.py --n 300` | `docs/benchmarks.md` regenerated at commit `f707ee2` (hot path unchanged since) |
| 24 | fresh clone, cold cache, README followed literally | `docs/first-user-test-v2.md`: 37 s to first allow/deny; 65 s to a passing regression test; one finding (destructive tools denied by default) folded into the README |
| 25 | `scripts/record_demo.py` | transcript + SVG regenerated from a real run |

## GitHub Actions (after publication)

The repository was published to https://github.com/TimelessVisions/agent-trust-plane
on 2026-09-17 (commit `16d937c`, tag `v0.3.0`). The first CI run on that
commit failed in one step on all three OS legs: `atp demo wrap --out
eval-reports/wrap-demo` resolved a *relative* `--out` twice (its `atp`
subprocesses run with `cwd=out`), which local runs with an absolute temp
directory never exercised. Everything before that step (lint, mypy, the
full test suite, evals, doctor, demos A–C) had passed on all legs. The fix
and a regression test landed as commit `a4ac997` on `main`.

GitHub Actions run: https://github.com/TimelessVisions/agent-trust-plane/actions/runs/35234834560 (commit `a4ac997`)

| Job | Result |
|---|---|
| backend (ubuntu-latest, Python 3.12) | PASS |
| backend (ubuntu-latest, Python 3.13) | PASS |
| backend (windows-latest, Python 3.13) | PASS |
| package (wheel build, isolated `uvx` run, pip-audit, SBOM) | PASS |
| dashboard (typecheck, production build) | PASS |

Still not verified: macOS; any IDE MCP client; PyPI publication (nothing
has been published to PyPI). The `v0.3.0` tag still points at `16d937c`,
i.e. before the demo fix; only `main` carries the fix.

## PyPI readiness check (2026-09-17, no upload performed)

| Check | Result |
|---|---|
| PyPI name `agent-trust-plane` (and `agent_trust_plane`, `agenttrustplane`) | unregistered (HTTP 404 on the JSON API). Unrelated `agent-trust-sdk`, `agent-trust-stack`, `agent-trust-mcp` exist under other owners; `atp` and `atp-core` are taken by unrelated projects (CLI name kept; distribution name differs) |
| Rebuild from `git archive v0.3.1` (twice) vs GitHub Release assets | byte-for-byte identical: wheel `cc5bd8dd…39d2731`, sdist `dec67508…038b7fe` (hatchling normalises archive timestamps to 2020-02-02) |
| Wheel/sdist contents | 98 / 111 entries; 11 import packages + `LICENSE`; no `.env`, `keys.env`, `.db`, `.atp/`, tests, caches, images, node_modules, git metadata; no private paths or secret-shaped strings in packaged code; no install-time hooks or dynamic version logic; `subprocess` only in `atp_cli/demos.py` (runs its own CLI) |
| `twine check` on v0.3.1 artifacts | PASSED (Markdown renders) — but ~30 relative links and the hero image do not resolve on pypi.org |
| Metadata of v0.3.1 artifacts | Version 0.3.1, License-Expression MIT, License-File, Requires-Python >=3.12, 7 public deps, `atp` entry point; **no Project-URL, Keywords or Classifier** |
| Clean install matrix (fresh venvs, cold uv cache, empty cwd, no `ATP_*`, repo not on `sys.path`) | Python **3.12, 3.13, 3.14** on Windows: install, `atp --help`, `atp doctor`, `atp demo injection`, `atp demo regression`, `atp demo mcp`, `atp demo wrap --out out/wrap` all exit 0; `importlib.metadata.version` = 0.3.1 |
| `uvx --isolated --from <wheel> atp doctor` / `atp demo mcp` | OK |
| `pipx run --spec <wheel> atp doctor` (pipx 1.17.3 via `uvx pipx`) | OK |
| bare `uvx agent-trust-plane` | not possible with v0.3.1 (only the `atp` executable exists); fixed on `main` by a second console script |
| Linux dependency licenses (resolved for x86_64 Linux / Python 3.12) | 41 distributions, all permissive; see `licensing.md` |
| `pip-audit 2.10.1` on the Linux-resolved pins (`--no-deps --disable-pip`, PyPI advisory DB via OSV, 2026-09-17) | No known vulnerabilities found; `uvloop 0.22.1` also queried directly at api.osv.dev: none |
| Private/local dependency scan | `Requires-Dist` contains only public PyPI names with version ranges; no `file://`, path, git or workspace references; workspace members are bundled into the single wheel |
| Trusted Publishing | pending-publisher flow researched (docs.pypi.org, 2026-09-17); workflow prepared, not enabled on PyPI |

Conclusion: **NO-GO for publishing v0.3.1 to PyPI** (presentation defects
that cannot be fixed without new artifacts); **GO-ready path** is v0.3.2 from
`main` after the metadata/README changes and the Trusted Publisher are in
place — see `pypi-publishing.md`.

## v0.3.2 release preparation (2026-09-17, Windows 11, local; no upload performed)

Tag `v0.3.2` → commit `5953f019b8855c234b21fc10a027ad18463e9700`
(GitHub Actions run 35266340358: all five jobs green before tagging).
Built with the pinned backend (`hatchling==1.32.0`, `uv build --python 3.12`):

| Check | Result |
|---|---|
| Artifacts from `git archive v0.3.2` (two independent exports, Windows) | `agent_trust_plane-0.3.2-py3-none-any.whl` sha256 `66fdab1bbb5d9f3c8e0422adde15b75316505be4a735c63a3afce16159dd4d3c`; `agent_trust_plane-0.3.2.tar.gz` sha256 `c2511e58a4e89f5dd8f66207d7c6ba7e24e269debe7141992d63952d76772fe1`; both builds byte-identical |
| Same commit built by the CI `package` job (ubuntu-latest, run 35266340358) | sdist sha256 `c2511e58…772fe1` — **byte-identical** to the Windows build; wheel sha256 `fb6cc40edcccd7b334ee3d2049760a80403762bd4b793c3142d665e4b13b241b` — every entry's content, name, timestamp and permission bits identical to the Windows wheel; the only difference is the zip header `create_system` byte (0 on Windows, 3 on Unix) on each of the 98 entries. So the wheel is reproducible per OS family, the sdist across OS. The publish workflow builds on ubuntu, so the PyPI wheel is expected to be `fb6cc40e…` |
| Working-tree build before commit | differed from the tag build only because four source files in the Windows checkout carry CRLF endings that git normalises to LF on commit (`atp_identity/service.py`, `atp_policy/base.py`, `atp_policy/policies/payments.py`, `finance_agent/agent.py`); all checks below were re-run on the tag build |
| Metadata (wheel `METADATA` and sdist `PKG-INFO`) | Metadata-Version 2.5; Name `agent-trust-plane`; Version 0.3.2; License-Expression MIT; License-File LICENSE (copyright line `Copyright (c) 2026 George Gakravyi`); Requires-Python >=3.12; 6 Project-URL, 8 Keywords, 15 Classifier; 7 public `Requires-Dist`; console scripts `atp` and `agent-trust-plane` both → `atp_cli.main:main` |
| `twine check --strict` (twine 7.0.0) | PASSED for wheel and sdist |
| `scripts/check_dist.py --version 0.3.2` | OK (98 wheel / 111 sdist entries; 11 packages + `py.typed`; no forbidden names; no secret/local-path patterns; no non-index dependency; no relative link in the long description) |
| README targets as rendered on PyPI | every link is an absolute GitHub URL; all 31 repository targets exist on `main` and the sampled ones (hero SVG on raw.githubusercontent.com, threat model, demos, first-user test, why-atp, competitive research, contributing, security, changelog, ADR and regression-suite directories) return HTTP 200 |
| Content scan (independent regex over every file in both artifacts) | only hits: the author's name/email in LICENSE, pyproject and metadata (intentional) |
| Clean install matrix (fresh venvs, cold uv cache, empty cwd, no `ATP_*`, repo not on `sys.path`) | Python **3.12.10, 3.13.14, 3.14.6**: install, `agent-trust-plane --help`, `atp --help`, `atp doctor`, `atp demo injection`, `atp demo regression`, `atp demo mcp`, `atp demo wrap --out relative/path` all exit 0; `importlib.metadata.version` = 0.3.2. Repository-only test `atp test examples/regression-suite/accounts-payable.yaml` (run from the checkout with each venv's `atp`) exit 0 |
| `uvx --isolated --from <wheel>` | `agent-trust-plane --help`, `agent-trust-plane doctor`, `agent-trust-plane demo mcp`, `atp --help` all OK. Note: with the uv cache under a very long path the notes server subprocess failed with a Windows MAX_PATH error (`jsonschema_specifications/…/format-annotation`), which is an environment limit, not a package defect; with a short cache path everything passes |
| `pipx run --spec <wheel>` (pipx via `uvx pipx`) | `agent-trust-plane doctor`, `atp --help` OK |
| Linux dependency resolution (x86_64 Linux / Python 3.12) | 40 pins, byte-identical (name-normalised) to the set license-reviewed for v0.3.1 on 2026-09-17; no dependency change |
| `pip-audit` on those pins (`--no-deps --disable-pip`, 2026-09-17) | No known vulnerabilities found; `uvloop 0.22.1` at api.osv.dev: none. "No known advisories", not a security guarantee |
| Repository gate (`scripts/check.sh` steps) | ruff: All checks passed; ruff format: 190 files already formatted; mypy strict: no issues in 76 files; pytest: 439 passed, 1 skipped (opt-in third-party MCP server test); with `ATP_E2E_NPX=1`: that test passes too; evals 8/8; doctor; demos A–D; sample suite; link checker 72 files / 0 broken; dashboard typecheck and production build OK |
| Secret scan of tracked files (`detect-secrets`) | one hit: the SHA-256 of the empty string in `packages/core/tests/test_core_models.py` (well-known constant; tests are not shipped) |
| Workflow lint (`actionlint`) | `publish.yml`, `ci.yml`: no findings |
| Action pins (GitHub API) | checkout `11d5960a…` = v4.4.0; setup-uv `d4b2f3b6…` = v5.4.2; upload-artifact `ea165f8d…` = v4.6.2; download-artifact `d3f86a10…` = v4.3.0; pypa/gh-action-pypi-publish `dc37677b…` = v1.14.2 (latest release as of 2026-09-17) |

`publish.yml` review findings fixed before tagging: the tag was
interpolated into a shell before validation and the `case` glob accepted
`v1.2.3;echo pwned` (now `env` + anchored regex); no released-commit
check (now `HEAD == github.sha` for release events); no artifact digest
re-verification in the publish job (now `sha256sum -c --strict`); build
backend unpinned (now pinned); pre-releases not refused; `twine`
unpinned; no job timeouts.
