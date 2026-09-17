# Current state — forensic review (2026-09-17)

Method: `git log`, `git status`, every source module, every test file, the
CI workflow, the docs tree and the ignored files were read; the full
validation suite was run before any change. Nothing below is taken from the
previous implementation report; each claim was re-checked against the tree
at commit `72d7862` (tag `v0.2.0`, branch `main`, no remote).

## Validation run before touching anything

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 124 files already formatted |
| `uv run mypy` (strict) | Success: no issues found in 66 source files |
| `uv run pytest` | **328 passed, 1 skipped** in 42.5 s (skip = opt-in npx test) |
| `ATP_E2E_NPX=1 uv run pytest adapters/mcp/tests/test_proxy_third_party.py` | 1 passed (reference `@modelcontextprotocol/server-filesystem`, Node 24.18) |
| `uv run python -m atp_evals` | 8/8 passed |
| `uv run atp doctor` | all checks ok (Python 3.14.6, uv, packages, temp, port, node, .env) |
| `uv run atp demo mcp` | exit 0; write allowed+executed, delete denied, file intact |
| `uv run atp test examples/regression-suite/accounts-payable.yaml` | 8/8 under payments-v2, exit 0 |
| `cd apps/dashboard && npm run typecheck` | clean |

Test functions by file (parametrised cases expand to 328): identity
security 31, red team 28, delegation invariants 24, gateway API 19, policy
engine 19, core models 17, regression 15, grants 8, trace store 7,
interceptor 7, finance agent 6, eval suite 6, CLI 5, proxy e2e 4, scope 4,
http client 3, third-party 1 (opt-in).

## What actually exists

A uv workspace of eleven Python packages (12.7 k lines including tests) and
one Next.js app (1.3 k lines of TS):

| Package | Role | Lines (src) | Verdict |
|---|---|---|---|
| `atp-core` | `ActionEnvelope` (frozen, `extra=forbid`, 16 KiB argument cap, `action_hash` over canonical JSON), `Decision`, `ReasonCode` (65 codes), `Money` (2 dp), `EffectiveAuthority` | ~600 | Solid. The protocol-neutral core already exists and has no MCP/HTTP imports. |
| `atp-identity` | Bearer credentials (`atpa_<id>.<secret>`, SHA-256 at rest, constant-time compare, expiry, revocation); delegation grants; chain resolution with cycle/depth/expiry/revocation checks; issuance validated against the parent's *effective* authority; chain intersection | ~800 | Solid. Root must be a human self-grant; child narrows only. |
| `atp-policy` | `Policy` ABC, `PolicyEngine` (evaluate all applicable, first DENY wins, else first REQUIRE_APPROVAL, else ALLOW), two built-in sets `payments-v1/v2`, `VendorDirectory` | ~700 | **Under-engineered for the product.** Every policy is a Python class hard-wired to `payments.send_payment`. There is no way to define a policy set without editing the repo; `mcp.*` tools get only capability + resource scope. |
| `atp-audit` | Hash-chained append-only trace store (memory + SQLite), integrity verification | ~350 | Solid for what it claims; chain is recomputable by a DB writer (documented). |
| `atp-gateway` | `TrustPlane` service (authorize/execute/replay/report_outcome under one RLock), FastAPI routes, HMAC-SHA256 single-use grants with server-side `issued→consumed`, settings that refuse insecure persistent configs, `LocalGateway` (uvicorn in a thread), `ExternalTool` release/outcome protocol | ~1900 | Solid. Security logic lives in `service.py`, not in handlers. |
| `atp-adapter-http` | `TrustPlaneClient` (sync httpx; ASGI in-process transport; agent/operator role helpers) | 284 | Adequate; returns raw dicts for most reads. |
| `atp-adapter-mcp` | stdio MCP proxy on MCP Python SDK 2.2 lowlevel `Server`; tools/list filtering; tools/call → authorize → execute(release) → upstream → outcome | 306 + 176 | Real and verified over the wire. `interceptor.py` (`McpInterceptor`) is the v0.1 in-process shim: still exported and tested, **unused by the proxy**, referenced only by `docs/architecture.md`. |
| `atp-evals` | 8 adversarial scenarios + regression suite format/runner/recorder | ~1100 | Solid. `record` requires a *running* gateway and the operator key. |
| `atp-cli` | `atp doctor/demo/test/record/serve/keygen/mcp-proxy/mcp-init` | ~670 | Works. `mcp-init` writes a static template with `REPLACE_WITH_GRANT_ID`; there is no path from "I have an MCP server" to "it is wrapped" without the user first running a gateway, issuing a credential and a delegation by hand. |
| `finance-agent` | Deterministic simulated AP agent + optional Claude agent (untested) | ~500 | Demo only. |
| `notes-mcp-server` | Harmless MCP server (list/read/write/delete notes in a directory) | ~80 | Good fixture. |
| `apps/dashboard` | Next.js operator UI: before/after replay, decision panel, delegation chain, timeline, eval grid | 1283 | Works; typechecks; not covered by tests. `ArchitectureFlow.tsx` and `EvalGrid.tsx` are decoration. |

Dependencies: 69 locked distributions; runtime core is fastapi, pydantic,
pydantic-settings, uvicorn, httpx, pyyaml, mcp (2.2.0), anyio. No
cryptography beyond `hmac`/`hashlib`. No Hypothesis.

## What actually works (verified today)

- Authorize → single-use grant → execute exactness (hash-bound), audience,
  expiry, revocation re-check under the lock, 8-thread race → one side effect.
- Delegation chains rooted at a human; child cannot widen capabilities,
  scope, amount, currencies or expiry; effective authority is the
  intersection.
- MCP interception over stdio, three processes, against the in-repo notes
  server and the reference filesystem server; unmapped tools hidden and
  denied; oversized arguments refused.
- Replay of a recorded decision under another policy set using the
  *recorded* authority snapshot; never executes.
- YAML regression suites → ephemeral gateway → `/authorize` only → text /
  JSON / JUnit; exit codes 0/1/2.
- Trace → case conversion with strict validation (hostile trace tests).

## What is partial

- **Policy authoring**: only two built-in sets; no user-defined sets; no
  generic argument constraints for non-payment tools (O16).
- **Resource scoping**: patterns are `<type>:<id>`, `<type>:*` or `*`. No
  prefix/path scope, so "anything under `/workspace`" is not expressible;
  the filesystem e2e test scopes a single exact path.
- **`REQUIRE_APPROVAL`**: recorded, never completable (no approver, no
  endpoint).
- **MCP**: stdio only, one upstream, `tools/list` + `tools/call`; no
  Streamable HTTP either side; prompts/resources not proxied;
  `input_required`/task results refused.
- **Explainability**: the decision carries every evaluation and constraint,
  but nothing renders "what would need to change".
- **Regression workflow**: `record` needs the gateway URL + operator key;
  there is no offline path from a trace to a case.
- **Dashboard**: operator key typed into the browser and held in a module
  variable; no CSRF concern (no cookies) but no session handling either.
- **Packaging**: nothing builds as a single installable distribution; the
  CI example installs the CLI from a git tag and was never exercised
  against a remote.

## What is unused or duplicated

- `atp_adapter_mcp.interceptor.McpInterceptor`, `AgentContext`,
  `DEFAULT_MAPPINGS`: v0.1 in-process path, superseded by the proxy;
  `ToolMapping` (used by the proxy) lives in the same module.
- Envelope construction is duplicated between `interceptor.to_envelope`,
  `proxy._envelope_for` and `regression.runner._envelope`.
- `scripts/demo.sh` starts the gateway with `python -m atp_gateway --port`
  and calls `POST /evals/run` without an operator key: **stale** (reads are
  operator-only since v0.1.1; the CLI is `atp serve`).
- `docs/README-v0.1.md` (407 lines) is an archived README kept for
  history; `docs/commercial-offer.md`, `docs/agent-production-readiness-audit.md`,
  `docs/prospect-message.md`, `docs/linkedin-case-study.md`,
  `docs/portfolio-case-study.md`, `docs/launch-post.md` are marketing/
  portfolio material sitting in the technical docs root.
- `docs/architecture.md` still draws `McpInterceptor` as the MCP adapter.
- `eval-reports/` is gitignored but present locally with stale runs.

## Overly complex / under-engineered

- Overly complex: `PolicyEngine` special-cases `PaymentApprovalThresholdPolicy`
  to find the approver role (an `isinstance` in the engine). The engine
  should ask the evaluation, not the policy class.
- Under-engineered: the policy layer (see above); the CLI has no
  machine-readable mode except `test --json`; errors from `mcp-proxy` with
  a bad config are Python tracebacks.

## Stale docs and comments

- `docs/architecture.md`: MCP adapter drawn as in-process interceptor.
- `scripts/demo.sh`: wrong entrypoint, unauthenticated eval call.
- `packages/cli/src/atp_cli/main.py` docstring lists `mcp-proxy`/`mcp-init`
  but the README tells users to run `atp keygen`, `atp serve`, then edit YAML
  by hand — the "one config change" claim in ADR-0002 is not what a user
  experiences.
- `docs/security-review.md` header says "as of commit e18d86b"; the v0.2.0
  additions are appended but the scope line was not updated.

## Architectural inconsistencies

- The proxy authorizes with an envelope whose `tool` is `mcp.<server>` and
  whose `resource` is template-derived; the regression suite pins that
  string. A rename of `server_name` silently invalidates every recorded case
  (cases are pinned to the literal tool name — acceptable, but undocumented).
- `Decision.matched_policy` is `None` for ALLOW even though evaluations
  record every pass; explain/diff tooling will need the full evaluation
  list, which is present.
- `trace_id` is 12 hex chars from `new_trace_id()`; case names, suites and
  the dashboard treat it as opaque, fine, but the format pattern is
  duplicated in four places.

## Security-sensitive code paths (read line by line)

- `atp_gateway/service.py`: `_bind_identity`, `_check_credential_live`,
  `_check_trace_owner`, `_authorize`, `_execute`, `_verify_grant`,
  `report_outcome`, `_replay`. All state changes under `self._lock`.
- `atp_gateway/grants.py`: HMAC mint/verify, canonical-body check, atomic
  SQLite conditional `UPDATE ... WHERE status='issued'`.
- `atp_gateway/auth.py`: bearer parse, operator key compare
  (`secrets.compare_digest`, checked).
- `atp_identity/credentials.py`: token format, hashing, constant-time compare.
- `atp_identity/service.py`: `resolve`, `_check_against_parent`, `_intersect`.
- `atp_identity/scope.py`: pattern grammar and `covers`.
- `atp_adapter_mcp/proxy.py`: `_bounded` (refuse, never truncate),
  `_envelope_for` (resource sanitisation), forward only after `released`.
- `atp_evals/regression/format.py`, `record.py`: strict models over
  untrusted traces; YAML via `safe_load`.

## Dependency risks

- `mcp` 2.2.0 is pre-1.0-style fast-moving (API differs from 1.x); the proxy
  pins `>=2.2,<3`. Any protocol-level change lands here.
- `pyyaml` `safe_load` everywhere (checked: no `yaml.load`).
- Python ≥ 3.12 required; CI tests 3.12/3.13; the maintainer runs 3.14.
- No dependency audit (`pip-audit`) or SBOM in CI.
- GitHub Actions use floating major tags (`@v4`, `@v5`), not SHA pins.

## DX friction (measured against the README)

1. Wrapping a real MCP server requires: `keygen --write .env`, `atp serve`
   in one terminal, issuing a credential with the operator key via HTTP,
   issuing a root delegation and a child delegation via HTTP, editing
   `atp-mcp.yaml`, exporting the token, then `atp mcp-proxy`. Seven manual
   steps, four of them raw HTTP. `atp demo mcp` hides all of this, which
   means the demo does not teach the real workflow.
2. `atp record` needs the gateway URL and the operator key; there is no
   "from the local store" path.
3. There is no `atp policy …` at all: no explain, no diff, no impact.
4. Nothing can be installed with `uvx`/`pipx`; the repo must be cloned.
5. Errors for a malformed proxy config are tracebacks.
6. The CLI name `atp` collides with nothing on this machine, but see the
   name research in `docs/research/`.

## Summary of the honest position

The security kernel (envelope → delegated authority → deterministic
decision → hash-bound single-use grant → hash-chained evidence → replay) is
real, tested and cleanly layered. The product around it is thin: policies
cannot be authored, resources cannot be scoped by prefix, the MCP path needs
seven manual steps, and the regression loop needs a running gateway. The
work that follows targets exactly those gaps; the kernel is kept as is.
