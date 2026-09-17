# Contributing

Thanks for looking. This is an experimental MVP with a narrow, security-
sensitive scope; contributions that keep it narrow and honest are the most
welcome kind.

## Setup

```bash
git clone <repo> && cd agent-trust-plane
uv sync                                  # Python 3.12+, uv
uv run atp doctor
cd apps/dashboard && npm install         # optional, dashboard only
```

## Checks (run all before a PR)

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy                              # strict, every src tree
uv run pytest -p no:warnings             # ~470 tests incl. property tests and MCP e2e
uv run python -m atp_evals               # 8 adversarial evals must stay 8/8
uv run atp test examples/regression-suite/accounts-payable.yaml
uv run atp demo wrap
uv run python scripts/check_links.py
cd apps/dashboard && npm run typecheck && npm run build
```

`scripts/check.sh` / `scripts/check.ps1` run all of the above. CI runs the
same set on Python 3.12 and 3.13 (ubuntu) and 3.13 (windows), builds the
wheel, installs it with `uvx`, audits dependencies and writes an SBOM.

Read `DEVELOPMENT.md` for the module map, the invariants, and how to add a
rule kind, a policy, an adapter or an identity provider.

## Ground rules

- **Do not weaken a security property to make a test pass.** The properties
  are listed in `docs/architecture/design-principles.md`; changing one needs an ADR in
  `docs/adr/`.
- **Every security claim needs a test.** If you add a control, add the attack
  it stops to `services/gateway/tests/test_identity_security.py` or
  `test_red_team.py`.
- **No mocks in evals.** Evals and regression suites drive the real routes.
- **Secrets never appear in traces, logs, responses or tests.** There is a
  test for that; keep it passing.
- **Keep packages small.** Dependency direction is `core ← identity ← policy`,
  `core ← audit`, everything else on top. The gateway must not import evals
  except lazily for `/evals/run`.
- Typed (`mypy --strict`), formatted (`ruff format`), documented where the
  behaviour is not obvious from the code.

## Where help is genuinely useful

See `docs/good-first-issues.md` for scoped items. Larger areas, roughly in
order of value:

1. A second `IdentityProvider` (SPIFFE/mTLS or OIDC client credentials) behind
   the existing protocol, selectable from settings.
2. Streamable HTTP *served* by the proxy, with client auth.
3. A `TraceStore` wrapper that streams events to an external sink.
4. Interceptor/ext_authz adapters for Docker MCP Gateway and agentgateway.
5. Postgres store implementations behind the existing interfaces.
6. Chaos tests for the proxy (killed mid-call) and a second SQLite writer.

Contributions are reviewed within a week where possible; issues without a
reproduction may be closed with a request for one.

## Pull requests

- One change per PR; describe the security implication if any.
- Add or update tests; update `CHANGELOG.md` under "Unreleased".
- If you touch policies, update the sample regression suite and say why the
  expected decisions changed.

## Releases

See `docs/release/releasing.md`.
