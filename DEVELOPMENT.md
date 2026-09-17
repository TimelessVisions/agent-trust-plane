# Development

## Module map (read this before changing anything)

```
packages/core/       atp_core          envelope, decision, reason codes, money, resource grammar, canonical JSON, bounded reads, sqlite unit-of-work
packages/identity/   atp_identity      credentials + IdentityProvider, delegation grants, chain resolution/intersection, scope algebra
packages/policy/     atp_policy        Policy ABC, engine, built-in payment sets, declared YAML sets, explain, diff/coverage
packages/audit/      atp_audit         hash-chained trace stores (memory, SQLite), verification
services/gateway/    atp_gateway       TrustPlane kernel (authorize/execute/replay/outcomes), grants, FastAPI routes, settings, wiring, LocalGateway + InProcessAgentClient, evidence bundles
adapters/http/       atp_adapter_http  AgentClient protocol, TrustPlaneClient (HTTP / in-process ASGI)
adapters/mcp/        atp_adapter_mcp   MCP proxy (served over stdio; stdio or Streamable HTTP upstream), tool mapping + path normalisation, config, discovery (init)
packages/evals/      atp_evals         adversarial eval scenarios; regression suite format/runner/recorder; impact + mutation analysis
packages/cli/        atp_cli           `atp`: doctor, demo, mcp init/wrap/proxy, trace, regression, test, policy, mutate, evidence, serve, keygen; the .atp/ home
examples/            notes-mcp-server (annotated tools), finance-agent (simulated AP agent), regression-suite, github-action
apps/dashboard/      Next.js operator UI (frozen at before/after evidence)
benchmarks/, scripts/, docs/
```

Dependency direction: `core ← identity ← policy ← gateway ← {cli, evals}`; `adapters/http` depends on core only; `adapters/mcp` on core + http; `gateway.local` on http. The kernel never imports `mcp` (`test_kernel_does_not_import_mcp_or_the_proxy`).

## Invariants you must not break

From [docs/architecture/first-principles.md](docs/architecture/first-principles.md); each has tests named in [docs/formal/grant-lifecycle.md](docs/formal/grant-lifecycle.md) and [docs/red-team/architecture-attacks.md](docs/red-team/architecture-attacks.md):

1. Nothing in an envelope is authority; identity comes from the provider, authority from the chain.
2. A child grant only narrows its parent (all dimensions).
3. A grant is minted only on ALLOW, binds the exact action hash and the agent, and is consumed once.
4. Replay, `atp test`, `policy impact`, `mutate` never call `execute`.
5. Unknown/unmapped/malformed ⇒ deny, never truncate or guess.
6. Every kernel step is on the trace before its side effect; identity rejections stay on the record even when the operation fails.
7. Shadow mode is a gateway setting; a caller can never request it; shadow denials are labelled everywhere.
8. Policies are deterministic functions of (envelope, authority snapshot, directory, clock); no model, no network.

## Running checks

```bash
uv sync                                   # dev dependencies (hypothesis, ruff, mypy, pytest)
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict
uv run pytest -p no:warnings              # ~2 min; includes property tests and MCP e2e
ATP_E2E_NPX=1 uv run pytest adapters/mcp/tests/test_proxy_third_party.py   # needs node/npx
uv run python -m atp_evals                # 8 adversarial evals
uv run atp demo wrap && uv run atp demo injection && uv run atp demo regression && uv run atp demo mcp
uv run python scripts/check_links.py
uv run python benchmarks/authz_overhead.py --n 300 --out docs/benchmarks.md
uv build && uvx --isolated --from dist/*.whl atp doctor
scripts/check.sh   # or scripts/check.ps1: everything above except the benchmark
```

`pytest` uses `--basetemp=.pytest-tmp` because the default temp root is unreadable on some Windows setups.

## How to add …

**A declared rule kind.** `atp_policy/declarative.py`: add the literal to `RuleKind`, validate its fields in `RuleSpec._shape`, evaluate it in `DeclaredRule.evaluate` returning a `ConstraintEvaluation` with `requested`/`limit`, add a reason code in `atp_core/reasons.py`, teach `atp_policy/explain.py` what would need to change, and `analysis.coverage_for` which dimension it guards. Tests in `packages/policy/tests/test_declarative.py`. Do not add expressions or regex.

**A built-in policy class.** Subclass `Policy` in `atp_policy/policies/`, keep `evaluate` pure, record every comparison as a `ConstraintEvaluation`, add it to a *new* policy-set version (never change an existing version's behaviour: suites pin versions).

**An adapter (another protocol).** Build envelopes from the protocol's call, call `AgentClient.authorize`/`execute`/`report_outcome`, treat the protocol's metadata as untrusted, fail closed on anything you cannot map. Look at `atp_adapter_mcp/proxy.py` (300 lines) and its e2e tests. Never put security rules in the adapter; they belong in the kernel.

**An identity provider.** Implement `atp_identity.provider.IdentityProvider` (headers only; never the body). See `docs/security/identity-providers.md` and the test with a second provider.

**An eval scenario.** `atp_evals/scenarios.py`: a deterministic scenario with named checks; run with `python -m atp_evals`.

**A store backend.** Implement the `Protocol`s in `atp_audit.store`, `atp_identity.store/credentials`, `atp_gateway.grants/tools/reports`; keep `consume` single-winner and commits routed through `commit_if_implicit`.

## Reporting security issues

[SECURITY.md](SECURITY.md). Do not open a public issue for a vulnerability.
