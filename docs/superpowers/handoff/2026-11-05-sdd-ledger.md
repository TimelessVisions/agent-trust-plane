# SDD ledger — ATP 1.0.0 (plan docs/superpowers/plans/2026-11-04-atp-1.0.0.md)

Branch: release/v1/B12-atp-1.0, from origin/release/v1/B11-bench-replay @ 34eb678 (plan says d88d20c; 34eb678 = d88d20c + plan commit).
Environment: Linux cloud container, Python 3.13.18, uv 0.11.32. Docker CLI present but no daemon. claude CLI 2.1.318 present; codex absent.

## Baselines (before any task)
- Root suite (junit): tests=467 failures=0 errors=0 skipped=1
- Bench suite (junit): tests=168 failures=0 errors=0 skipped=0 (578s)

## Rulings
Ruling: `.superpowers/` is excluded via .git/info/exclude, not .gitignore — the brief says the ledger is git-ignored and changing .gitignore is outside the plan — cost if wrong: one-line .gitignore change later.
Ruling: branch `v0.4-file-format-versions` does not exist on origin, so `docs/release/v1.0.0-plan.md` cannot be read; the 1.0.0 plan's own Interfaces sections are taken as the full spec for Phase C — they are detailed and the spec says the plan supersedes — cost if wrong: a frozen-surface detail from the v0.4 table missing from docs/stability.md (C9).

## Tasks

### A3 — DONE (34eb678..8e75755, plus c11af46 lint chore). Review: APPROVED, 0 blocking.
Bench junit: 186/0/0/0. Root junit: 467/0/0/1.
Ruling: Plan's DELEGATION_CAPABILITY_ESCALATION / DELEGATION_SCOPE_ESCALATION do not exist; mapped to DELEGATION_EXCEEDS_PARENT_CAPABILITIES / DELEGATION_EXCEEDS_PARENT_RESOURCE_SCOPE (+EXPIRED, REVOKED); other DELEGATION_* → INCONCLUSIVE — the listed names are not ReasonCodes — cost if wrong: one-line list change.
Ruling: Annotation validation (unknown tool/action, resource_args vs schema) runs at ATP render time; a bad annotation makes that task INCONCLUSIVE for the ATP layer only, with the reason in detail — never silent pass, never aborts the run — cost if wrong: errors only seen during runs.
Ruling: Rule tool must be exactly dojo.<suite> and action a real suite tool; wildcards rejected — a wildcard can't be checked and could widen a rule — cost if wrong: relax _check_annotation.
Ruling: Partial-journal guard compares journal lines with layer-ALLOWED calls per phase; unreadable journal → INCONCLUSIVE (was silently []) — a missing line must never read as "did not reach upstream" — cost if wrong: some pairs INCONCLUSIVE instead of scored.
Ruling: Fixed pre-existing bench ruff errors (root CI lints bench/) — CI must be green — cost if wrong: larger diff only.
Ruling: Excluded docs/superpowers from ruff (c11af46); ruff 0.16 formats Python blocks in markdown and the older plan's sketches failed the root format check at 34eb678 — plans are historical sketches — cost if wrong: sketch code unformatted.
Finding: all 97 ok-annotations pass the new render-time checks; no annotation errors.

### B1 — DONE (c11af46..2090553: 8c08b36 impl, 2090553 fix round 1). Review: APPROVED; fix-round re-review APPROVED.
Root junit: 475/0/0/1. Bench: full 186/0/0/0 (after 8c08b36).
Ruling: `atp mcp wrap` registers each mapping tool as a gateway external-executor prefix and refuses mappings onto gateway-run tools — without it a non-mcp. mapping tool fails at execute with TOOL_NOT_REGISTERED — cost if wrong: dojo.banking also releases dojo.bankingX in the wrap session's local gateway (policy still applies; reviewer verified named tools always win).
Ruling: Remote gateway mode unchanged; docs tell operators to add non-mcp. mapping tools to ATP_EXTERNAL_TOOL_PREFIXES (fails closed with TOOL_NOT_REGISTERED otherwise) — operator configuration — cost if wrong: remote users with custom mapping tools see denials until configured.
Ruling: Retarget test rewritten to assert rules pass through unchanged, not deleted — stricter — cost if wrong: none.
Ruling: ProxyConfig refuses mapping tools in GATEWAY_EXECUTED_TOOLS={"payments"} in every mode (fix round) — in remote mode a payments mapping would settle while the proxy reported "denied" — cost if wrong: drift test pins the constant to the gateway registry.
Ruling: wrap unions ATP_EXTERNAL_TOOL_PREFIXES with mapped tools instead of overriding — consistent with no-mapping behaviour — cost if wrong: env without mcp. no longer gets mcp. re-added.
Deferred minor: CHANGELOG line wrap; duplicate prefix dedupe in home.py (cosmetic).

### B2 — DONE (2090553..327f0b3: df74d43 impl, 327f0b3 review follow-up by controller). Review: APPROVED.
Root junit: 482/0/0/1. Bench full: 186/0/0/0. No annotation uses argument_required; argument_forbidden behaviour unchanged.
Ruling: argument_required deny message/explain hint now say "missing or null" (controller fix of review minor) — explain would otherwise say "provide x" when x was sent as null — cost if wrong: wording only.

### C1 — DONE (327f0b3..HEAD: 8fcc118 impl, dda9e80 fix round 1, then controller fix for JSON escapes). Review: CHANGES_REQUIRED → fixed → re-review found 1 Important (JSON path) → fixed by controller with test.
Root junit: 539/0/0/1. Bench full: 186/0/0/0 (after 8fcc118).
Ruling: "warn once per file" = process-wide set keyed by (kind, normcase(realpath)); only file loaders warn, never model_validate on dicts; private _reset_warned() + autouse root conftest fixture — same file via different paths warns once — cost if wrong: a re-edited file in a long-lived process won't warn twice.
Ruling: PolicyFile.version narrowed from int(ge=1,le=1) to Literal[1]; policy_sets[].version untouched — same meaning — cost if wrong: none.
Ruling: regression suites get the same version contract — C9 freezes regression-suite.yaml and migrate handles suites — cost if wrong: unversioned suites print a deprecation warning.
Ruling: `atp regression migrate` did not exist; added as an alias of `atp migrate` — nothing to reuse — cost if wrong: none.
Ruling: `atp`, `atp-mcp-proxy` and `python -m atp_gateway` install an "always" display hook for UnversionedFileWarning only (public atp_core.show_unversioned_file_warnings) — Python hides DeprecationWarning outside __main__ — cost if wrong: PYTHONWARNINGS=ignore cannot silence this one line.
Ruling: migrate never loses comments silently: it inserts after BOM/---/tag lines, writes through symlinks, and refuses with exit 2 + "add version: 1 by hand" when a comment-bearing file cannot be edited in place — cost if wrong: a few flow-mapping files need a manual one-line edit.
Ruling: migrate normalises version "1" and 1.0 to 1; other bad values exit 2 — the two near misses the review named — cost if wrong: manual edit for other near misses.
Ruling: JSON files are re-emitted with ASCII escapes, checked by JSON round-trip and YAML-loadability; otherwise refuse (exit 2) — atp loads JSON via YAML, which rejected raw U+0080 — cost if wrong: JSON with non-ASCII text now shows escapes.
Deferred minor: a file with mixed line endings gets CRLF on the inserted line; duplicate top-level version: keys leave a stale earlier line (loads correctly, last key wins).

### C2 — DONE (d074e1c..6cf7c64). Review: APPROVED (0 blocking, 5 minors; minors 1-4 handed to a follow-up commit before C3).
Root junit: 566/0/0/1. Demos wrap/injection/regression/mcp exit 0. Bench test_layers+test_run 40/0.
Ruling: HMAC grant key dropped after migration — it signed grants only; traces/evidence are keyless SHA-256 chains (tested) — cost if wrong: outstanding 0.3 grants at upgrade are rejected (plan accepts).
Ruling: cryptography>=50 declared in gateway and root pyproject (lock had 50.0.1) — root wheel bundles the gateway — cost if wrong: one line.
Ruling: retirement = sidecar keys/grant-<kid>.retired (ISO UTC); old key verifies until retired_at + current grant_ttl; old private key deleted at rotation — cost if wrong: TTL changes move the window.
Ruling: running gateway keeps its loaded key until restart; rotation tells the operator to restart — cost if wrong: late restart can reject grants before expiry (fails closed).
Ruling: token version `v` moved from claims to header; 0.3 grant rows load by dropping `v` — cost if wrong: version no longer stored per grant row.
Ruling: leak check also refuses ATP_HOME, ATP_GRANT_SIGNING_KID/KEYS_DIR, PEM keys and key paths in env/headers/args — cost if wrong: configs deliberately passing ATP_HOME upstream are refused.
Ruling: legacy HMAC-only setting makes a persistent gateway refuse to start with a migration message — fail closed — cost if wrong: one dead setting.
Known limit: two processes migrating the same old home concurrently each generate a key; last write wins (only wrap gateway signs today).

### C2 minors follow-up — 97fbcf7 (marker before env switch; future .retired rejected; docs; leak check flags ATP home/parents). Reviewed with C3: APPROVED.
### C3 — DONE (97fbcf7..db80fb6). Review: APPROVED (6 minors; tests/doc minors 1-4 handed to step 0 of C4).
Root junit: 586/0/0/1. Demos exit 0. Mutation checks: every named test fails with its feature disabled.
Ruling: approver roles from operator-set ATP_APPROVER_ROLES env map — no role concept existed — cost if wrong: operator-key holder can approve as anyone in the map; removing an approver does not revoke approvals already given (≤24h).
Ruling: added reason codes APPROVAL_DENIED, APPROVAL_EXPIRED, APPROVAL_INVALID, APPROVAL_NOT_REQUESTED, APPROVAL_ALREADY_DECIDED, APPROVER_ROLE_MISSING (+ planned APPROVAL_ALREADY_USED) — distinct stable codes — cost if wrong: more frozen codes at 1.0.
Ruling: one approve/deny per trace, final — cost if wrong: changing mind needs a new trace.
Ruling: proxy caches REQUIRE_APPROVAL envelopes keyed by SHA-256(canonical tool+args), max 256, re-sends same envelope on identical retry (action_hash covers envelope/trace ids) — cost if wrong: per-process cache lost on restart.
Ruling: trace view keeps the first decision (REQUIRE_APPROVAL); ALLOW visible in events — replay stability — cost if wrong: trace list under-reports approved executions.
Process note: C3 tests were written after the code (implementer admitted); reviewer mutation-tested each.

### C3 minors follow-up — ec48d64 (tests/docs only). 
### C4 — DONE (ec48d64..9b59a22: bb3b0a6 impl, 9b59a22 fix round 1). Review: CHANGES_REQUIRED (external-executor budget bypass $1200 through $500; replay false change) → fixed → re-review APPROVED.
Root junit: 641/0/0/1. Demos exit 0.
Ruling: store API is reserve(reservation_id, lines, amount, *, expires_at, now) -> ReservationResult (+usage/settle/release/hold/release_expired), not the plan's reserve(grant_id, period_start, amount) -> bool — one call must check every chain budget atomically and feed explain — cost if wrong: adapter needed.
Ruling: spend keyed per (root principal, grantee of the budget-setting grant), not grant id — wrap mints new grants per session — cost if wrong: two grants to the same grantee from one human share a count.
Ruling: every budget on the chain is checked independently (tightest wins, periods independent) — cost if wrong: EffectiveAuthority carries a list.
Ruling: only actions with an argument named exactly `amount` are budgeted; missing currency defaults to the budget's; invalid → PAYMENT_ARGUMENTS_INVALID — no common MCP money schema — cost if wrong: tools using other names (value, amount_cents) spend outside budgets (documented).
Ruling: currency mismatch → DENY PAYMENT_CURRENCY_NOT_PERMITTED, no conversion — fail closed — cost if wrong: multi-currency chains can't spend.
Ruling: external outcome settles at the reserved amount (reported lower actual not trusted) — cost if wrong: over-counts real spend.
Ruling: a reservation becomes "held" once its grant is consumed and is never auto-released; only never-used grants' reservations lapse at expiry; failure report/tool error releases; success settles — fix for the reviewer's bypass — cost if wrong: an executor that never reports locks budget until operator reconciles via the store (no CLI yet).
Ruling: settle on an already-released row counts as spent (reconciliation only; report_outcome refuses a second report) — money really moved — cost if wrong: operator-only path can push over limit.
Ruling: replay does not re-check budgets; a budget denial replays as no change unless policy itself now denies; ReplayResult.budget_reevaluated=false — cost if wrong: ALLOW→REQUIRE_APPROVAL behind a budget denial not flagged.
Ruling: amounts like "1e30" and whitespace-padded strings are invalid (PAYMENT_ARGUMENTS_INVALID) — cost if wrong: such inputs denied.
Open (handed to C5 step 0): outcome reports come from the grant's own agent credential, so a lying `succeeded=false` frees budget; and hold() with rowcount 0 under clock skew between two gateways should block execution.

### C4 follow-up 528576f (agent failure reports don't free budget; failed hold blocks). Reviewed with C5: sound.
### C5 — DONE (9b59a22..HEAD: 528576f, 7664425 impl, 7d6a486 fix r1, 6dc0e68 fix r2, + controller doc wording). Reviews: CHANGES_REQUIRED (re-sign ran every ensure) → r1 → CHANGES_REQUIRED (DB writer deletes marker row) → r2 → verified by controller (674/0/0/1, lint clean).
Ruling: agent-reported failure keeps a held reservation; only operator-reported or gateway-observed failure releases; operator report refused after a success — the agent is the budgeted party — cost if wrong: honest executor failures hold budget until an operator confirms (HTTP only, no CLI).
Ruling: if hold() finds the reservation released (peer clock skew), execution is blocked with PAYMENT_EXCEEDS_BUDGET, remaining rows released, grant stays consumed — never run unbudgeted — cost if wrong: agent re-authorizes.
Ruling: revoked_at excluded from the signed root payload (with signature, signer_kid); canonical JSON from python-mode dump with sorted sets — revocation must not break signatures — cost if wrong: re-sign needed.
Ruling: root requests carry signer-chosen grant_id and issued_at (signed); duplicate id → DELEGATION_CHAIN_BROKEN — cost if wrong: error wording.
Ruling: AtpHome.ensure() creates the local human key (local-user or the atp-mcp.yaml principal) and runs a ONE-SHOT migration re-signing pre-1.0 unsigned roots of humans with a key in the home; marker file principals/.roots-migrated (0600) outside atp.db; fresh homes write it at creation; extra cutoff issued_at < key mtime (not a control vs DB writer, documented) — 0.3.2 homes keep working (C10) without letting a DB writer get roots signed — cost if wrong: other humans' 0.3 roots stay unsigned and denied.
Ruling: operator key still required to post a root, and the operator can issue children under a signed root (documented) — plan keeps children server-resolved — cost if wrong: operator acts below a human's signed root.
Ruling: ephemeral (:memory:) gateway auto-creates per-human keys for in-process signers only; persistent gateway without ATP_PRINCIPAL_KEYS_DIR denies every root — cost if wrong: :memory: gateways effectively unprotected (documented).
Ruling: principal key files named <id with ':'→%3A>-<sha256(id)[:12]>.key/.pub, created no-clobber (hard link, O_EXCL fallback), .pub re-derived from .key after a crash — case-insensitive FS and race safety — cost if wrong: file names change.
Fixed: benchmarks/authz_overhead.py (broken by C2's GrantSigner kid; not run by CI) runs again.

### C6 — DONE (e7ade96). C7 — DONE (66bd664). Joint review: APPROVED (5 minors; evidence minors 1-2 handed to C9 step 0).
Root junit: 683/0/0/1. Demos exit 0.
Ruling: evidence bundle v2 adds only `trace_format: "atp-trace/1"`; hash over fields present so 0.3 v1 bundles verify; v1 must lack trace_format, v2 must have it — nothing else changed since 0.3 — cost if wrong: more fields later.
Ruling: trace export format lives on TraceView (GET /traces/{id}, `atp trace show --json`); no `atp trace export` command exists — cost if wrong: new command later.
Ruling: 422 returns field paths only; approvals and payments errors stopped echoing values — residual: loc paths can contain client-chosen key names; 404 for /traces/<id> echoes the caller's own path id (minor, accepted).
Ruling: C7 hint names the config file by its real name (default gives the plan's exact line) — cost if wrong: one-line change.
### C8 — DONE (controller, ci: macOS leg). YAML lints; macOS run is NOT_MEASURED until the owner opens the PR.

### C6 minors follow-up — 8ebf961 (redactions required; trace_format Literal).
### C9 — DONE (bac92fa..5d5769a: 8ebf961, 71a5f52 impl, 5d5769a fix r1). Review: CHANGES_REQUIRED (exit-code table self-contradiction; coverage) → fixed (controller accepted fix round: wording + tests, 712/0/0/1, lint clean).
Ruling: frozen-surface list = spec goal 5 + plan additions (budgets, approvals, signed roots, exit codes) + docs/regression/schema-versioning.md table — v0.4 plan table missing — cost if wrong: H1 adds/removes rows.
Ruling: `atp policy impact` exits 0 when decisions change (1 only with --fail-on-widen on a widening); general exit-code row narrowed to "the command's own check failed", per-command list governs — departs from plan line 312 ("1 = a decision changed") because impact is a report — cost if wrong: one-line CLI change + doc/test.
Ruling: --json and HTTP shapes compared strictly (added key fails, a deliberate golden update); trace-export and evidence-bundle compared additively, as the contract says — cost if wrong: relax/tighten comparator.
Ruling: golden policies.yaml exercises every RuleKind and RuleSpec/PolicySetSpec field; generator deterministic (byte-identical across runs).
Process: Step 2 proof — renaming trace-list `last` key failed test_json_shape_unchanged; reverted (commit body of 71a5f52).

### C10 — DONE (5d5769a..HEAD: b89ab54 + .gitignore chore). Review: APPROVED. Fixture is a real PyPI agent-trust-plane==0.3.2 home (re-generation confirmed structure). Upgrade needed no product fixes.
Root junit: 713/0/0/1.
Ruling: fixture's .atp committed as dot-atp/ (renamed back at test time) with a scoped .gitignore negation; SQLite side files stay ignored — .atp/ and *.db are ignored repo-wide — cost if wrong: throwaway demo keys in repo (MANIFEST says so; may trip secret scanners).
Ruling: 0.3.2 already wrote version: 1 in policies.yaml and the regression suite; only atp-mcp.yaml is unversioned → exactly one warning — what 0.3.2 really produced — cost if wrong: none.
Ruling: "start" tested via `atp mcp wrap` (calls ensure()); `atp trace list` alone migrates the key but not roots — roots are re-signed on first ensure(); offline commands don't check root signatures — cost if wrong: a read-only command rewriting keys.env is surprising; `atp approve` on an unmigrated home untested.
Ruling: fixture not byte-reproducible (0.3.2 has no seed); machine paths rewritten (command: python3, NOTES_DIR: notes).

### D1 — DONE (7a7ded9). Review: APPROVED (3 minors deferred: _install OSError→EnvBlocked, cache re-hash/race, docstring scope of EnvBlocked).
Bench full junit: 192/0/0/0. Pins verified against published checksums: agentgateway v1.6.0 linux-amd64 496ed27e…f079d (.sha256 asset); ToolHive v0.55.2 linux_amd64.tar.gz 4336f1fa…612f44 (checksums.txt).
Ruling: a layer raising EnvBlocked rewrites every item of that layer to ENV_BLOCKED (NOT_APPLICABLE kept), even items already measured — never mix partial numbers with blocked status — cost if wrong: partial results discarded (reviewer suggests noting count in reason).
Ruling: tool_pins.yaml is per-platform; sha256 is the published hash of the downloaded asset — cost if wrong: schema tweak.


### D2 follow-up candidate — 2026-11-05 (ENV_BLOCKED, NOT REVIEWED)

The optional patch at `docs/superpowers/handoff/2026-11-05-d2-fix-partial.patch` was applied to the agentgateway layer, binary-backed tests and competitor documentation on `release/v1/B12-atp-1.0`. Handoff-required tests were expanded for non-finite numbers, malformed and bounded resource IDs, numeric strings, Unicode code-point lengths, and a non-BMP literal. No annotations were changed. This is a candidate fix, **not** a verified D2 completion.

Ruling: preserve agentgateway v1.6.0's real argument-aware CEL enforcement, and treat the optional patch as unverified until its binary tests run — fairness requires the strongest documented/source-supported competitor policy — cost if wrong: CEL compilation/behavior mismatch or an unfair benchmark comparison.

- **ENV_BLOCKED:** This agent's container could not clone the repository: `fatal: unable to access 'https://github.com/TimelessVisions/agent-trust-plane.git/': Could not resolve host: github.com`. It could read and commit branch files via the linked GitHub connector, but had no complete local checkout or pinned agentgateway binary. The root and bench test suites, lint, and binary-backed tests were therefore **NOT_MEASURED** in this execution; no JUnit counts are claimed.
- **Required before D2 approval:** In a Linux environment with GitHub access, run the documented `bench/tests/test_agentgateway_layer.py` against pinned agentgateway v1.6.0, inspect JUnit counts, run both root and bench gates, obtain an independent code review, and fix any failures. Do not proceed to D3 on assumed success.

Ruling: binary-semantic comparison tests now raise an explicit `ENV_BLOCKED` assertion when the pinned binary cannot execute instead of silently returning a passing pytest result — a missing measurement must never look like a PASS — cost if wrong: environments without the pinned binary will show a failing benchmark test until properly provisioned.

### D2 verified candidate — GitHub Actions 41998777874 (2026-11-05)

**Branch-only, pinned-runner evidence:** [workflow run](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/41998777874), commit `a4b3496a8f7a0b9e64fdaf837de9d04a65e733e0`.

- **PASS** — D2 binary-backed JUnit: tests=9, failures=0, errors=0, skipped=0. The two mandatory binary semantic comparison cases executed. The pinned agentgateway v1.6.0 executable SHA-256 is `496ed27e6a96b55a9ad7cabe5c2be7172511f44a3cb113e533d22bf93a7f079d`, verified by the release-branch workflow.
- **PASS** — root JUnit: tests=713, failures=0, errors=0, skipped=1; Ruff lint, Ruff format, mypy, and wrap/injection/regression/MCP demos succeeded.
- **SKIP (explicit)** — `adapters/mcp/tests/test_proxy_third_party.py::test_reference_filesystem_server_behind_proxy`; JUnit reason: `set ATP_E2E_NPX=1 with npx on PATH to run the third-party server test`. It was not measured, not called PASS.
- **PASS** — full bench JUnit: tests=204, failures=0, errors=0, skipped=0; includes 97 annotation-utility tests and all 9 D2 test cases.
- Actual XML was inspected from `atp-v1-{root,bench,d2}-junit` workflow artifacts; counts above are not inferred from GitHub's green icon.
- The D2 review's six identified issues were addressed with the optional patch, binary tests and competitor document: finite numbers/NaN; valid 1–255-character resource IDs across all scope shapes; Unicode code-point string length; numeric-string approximations; non-BMP CEL literals; raw-body CEL and parser limits. Documented residuals remain, especially IEEE-double precision and large/non-ASCII numeric strings.
- **Review status:** the previous CHANGES_REQUIRED items have executable coverage and an internal cross-agent source review; this is not an external audit. No benchmark attack sweep was run and no benchmark success-rate numbers are claimed.
- **Gate status:** D2 development verification PASS; release publication remains owner-gated. D3 may begin under the binding plan. The `bench-annotations-v1` tag and all owner gates remain untouched.

Ruling: finish D2 review from the exact binary-backed CI result and preserve its documented CEL approximations — every required review issue has a tested or explicitly qualified outcome, without weakening competitor policy — cost if wrong: a policy transformation can diverge from ATP semantics outside the pinned test set; the published results must continue to disclose those limitations.

### D3 and D4 verified candidates — GitHub Actions 42010172197 (2026-11-05)

**Source:** [all-five-jobs workflow run](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/42010172197), commit `1986e121e8be1dc2220944425de7eaf396bb8e2f`. Checks ran on `release/v1/B12-atp-1.0`, without a PR, merge, tag or publication.

- **PASS** root JUnit: tests=713, failures=0, errors=0, skipped=1. The previously documented opt-in third-party filesystem test remains the one skip; lint, Ruff formatting, mypy and four demos succeeded.
- **PASS** full AgentDojo benchmark JUnit: tests=215, failures=0, errors=0, skipped=0.
- **PASS** D2 pinned agentgateway v1.6.0 JUnit: tests=9, failures=0, errors=0, skipped=0; verified binary SHA256 `496ed27e6a96b55a9ad7cabe5c2be7172511f44a3cb113e533d22bf93a7f079d`.
- **PASS** D3 pinned ToolHive v0.55.2 JUnit: tests=8, failures=0, errors=0, skipped=0; verified binary SHA256 `894a8d563d95dd045919cd03da0375c59f104bd506d592760f01277399a04a0f`. Real Docker runner ran pinned `thv`, allowed a bill file read and in-scope payment at 98.70, denied an over-limit payment (99), a wrong-recipient payment and an ungranted `update_password`. Raw journal names: `["read_file","send_money"]` only. The D3 job required a nonempty successful E2E proof, so ENV_BLOCKED alone could not pass the gate.
- **PASS** D4 JUnit: tests=3, failures=0, errors=0, skipped=0. Name-only reference forwards an annotated tool even when its arguments violate scope; an ungranted tool is blocked before the journal. Mocked missing Docker daemon produces **ENV_BLOCKED** carrying stderr. **NOT_MEASURED:** no actual Docker MCP Gateway product run, denial response or real plugin proof. Never ascribe the name-only result to Docker.
- **Documented approximations:** ToolHive has scalar Cedar argument fields but no list-item inspection; 24 subset-of annotations across workspace/travel are dropped and individually recorded, with pinned source URLs. The ToolHive profile documents numeric-string/decimal and null/complex ambiguity; these are not equivalence claims.
- **Gate status:** D3 and D4 implementation/targeted runtime checks complete. D5 competitive attack sweep remains blocked by the owner's A1 annotation review/tag. E1 may proceed in task order; all publication gates remain in force.

Ruling: accept D3's measured ToolHive binary allow/deny behavior and D4's name-only negative-control evidence, while marking Docker MCP Gateway product behavior NOT_MEASURED — cost if wrong: reporting a synthetic baseline as a measured commercial product would invalidate the competitor comparison.
