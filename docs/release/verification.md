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
