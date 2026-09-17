# v0.3.0 verification record (2026-09-17)

Environment: Windows 11 10.0.26200, Python 3.14.6 (uv-managed), uv 0.9,
Node 24.18 / npm, MCP Python SDK 2.2.0. All commands run from the
repository root at the release-candidate tree; results copied from the
terminal. Linux/macOS: not run in this pass (no remote for CI yet).

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

Not verified (stated in `docs/integrations/compatibility.md`): Linux/macOS,
Python 3.12/3.13 on a remote runner, any IDE MCP client, PyPI publication.

Publication steps (repository creation, push, GitHub release, PyPI) were
**not** performed; they require the maintainer's explicit approval.
