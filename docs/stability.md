# Stability contract (1.0)

Status: **candidate**. Task H1 regenerates the golden files and marks this page
"Frozen at 1.0.0". From then on, a change to anything listed under
[Frozen surfaces](#frozen-surfaces) is a breaking change and needs a major
version (2.0). `tests/compat/` enforces it in CI.

**Everything not listed below is private.** It may change in any release,
minor or patch, without notice or deprecation.

## How the contract is held

- `scripts/gen_compat.py` runs one deterministic scenario (an `atp mcp wrap`
  session over the notes MCP server: one allowed `write_note`, one denied
  `delete_note`) with a fixed clock, ids and keys, and writes the golden files
  in `tests/compat/1.0/`.
- `tests/compat/test_compat.py` loads every golden file with the current code,
  reruns the scenario, and compares each JSON output key by key: the same keys
  and the same JSON types at every level. Values may differ. Reason codes may
  only be added. The checked-in evidence bundle and trace export must still
  verify.
- "Compatible" means: a file or payload that 1.0 wrote or accepted is read the
  same way by every 1.x, and a 1.x output has every key 1.0 had, with the same
  type and meaning.

Changes allowed in a 1.x minor release:

- new optional input fields with a default that keeps the old behaviour;
- new reason codes, trace event types, CLI commands and flags;
- new keys in JSON outputs only where the format below says "additive".
  The `--json` CLI outputs and the HTTP authorize response are compared
  strictly by the compat tests, so a new key there fails them; adding one is a
  deliberate golden-file update, reviewed as a contract change.

## Frozen surfaces

| # | Surface | Precisely | Golden file |
|---|---|---|---|
| 1 | **Action envelope schema** | The JSON body of `POST /authorize` and `POST /execute` (`envelope`): field names, types, required fields, and the `action_hash` it yields | `http/authorize-request.json` |
| 2 | **Authorization result** | The `POST /authorize` response: `decision` (every `Decision` field, `outcome` values `ALLOW` / `DENY` / `REQUIRE_APPROVAL`, `enforcement`, `evaluations`, `effective_authority`) and `execution_grant` (`token`, `grant_id`, `expires_at`). The grant `token` is opaque: its content is private, only its presence and use are frozen | `http/authorize-response.json` |
| 3 | **Reason codes** | Every `ReasonCode` value. Codes are never removed or renamed; new ones may appear | `reason-codes.txt` |
| 4 | **Trace export format `atp-trace/1`** | `GET /traces/{id}` and `atp trace show --json`: the `format` field, the event list, the event hash chain (`hash`, `prev_hash`, the canonical-JSON hashing rule) and `integrity`. Event types and payload keys are additive only; existing keys are never reinterpreted | `trace-export.json` |
| 5 | **Evidence bundles** | `bundle_version` 1 (0.3.x) and 2 (1.0) as written by `atp evidence export`; `bundle_hash` over the canonical JSON; `redactions` required in every version; `trace_format` (`atp-trace/1`) required in 2 and absent in 1. `atp evidence verify` accepts 1 and 2 and rejects any other version | `evidence-bundle.json` |
| 6 | **Policy file format** | `policies.yaml` with `version: 1`: `policy_sets[]` (`version`, `description`, `include`, `approval_threshold`, `rules`), the nine rule kinds (`argument_max`, `argument_min`, `argument_allowed_values`, `argument_subset_of`, `argument_max_length`, `argument_required`, `argument_forbidden`, `deny`, `require_approval`) and their fields, and what each rule decides | `policies.yaml` |
| 7 | **Regression-suite format** | Suite files with `version: 1`: `policy_set`, `policies`, `delegations` (`principals`, `grants`), `cases` (`expect`, `source`) | `regression-suite.yaml` |
| 8 | **MCP proxy config** | `atp-mcp.yaml` with `version: 1`: `server_name`, `upstream`, `authority` (`capabilities`, `resource_scope`, `expires_in`, `budget`), `policy_set`, `tools[]` mappings | `atp-mcp.yaml` |
| 9 | **Budgets** | The delegation constraint `constraints.budget` (`amount` as money with `currency`, `period`: `day`, `week` or `month`, UTC calendar periods) and the cumulative-budget rule: reserve at authorize, settle on success, release on failure or at grant expiry; `PAYMENT_EXCEEDS_BUDGET` as the denial | via 1, 2, 8 |
| 10 | **Approvals** | The `REQUIRE_APPROVAL` outcome, `approver_role` on `require_approval` rules, `POST /approvals/{trace_id}` and `atp approve TRACE --as ID [--deny] [--expires D]`, and the rule that an approval is bound to one `action_hash` and yields one grant | via 2, 6 |
| 11 | **Signed root delegations** | `POST /delegations` for a root grant must carry `signature` and `signer_kid` (Ed25519 by the human grantor's key over the grant's canonical JSON without `signature`, `signer_kid`, `revoked_at`); an unsigned root is `DELEGATION_ROOT_UNSIGNED`; `atp principal keygen HUMAN_ID` | via 3 |
| 12 | **CLI surface** | The commands and flags below, their `--json` output shapes, and the exit codes | `cli-json/*.json` |

### CLI surface

Frozen commands (names, positional arguments and the flags shown in
`atp <command> --help` at 1.0): `atp mcp init`, `atp mcp wrap`, `atp mcp proxy`,
`atp trace list`, `atp trace show`, `atp regression add`, `atp regression migrate`,
`atp test`, `atp record`, `atp approve`, `atp policy explain`, `atp policy diff`,
`atp policy impact`, `atp policy coverage`, `atp mutate`, `atp evidence export`,
`atp evidence verify`, `atp serve`, `atp migrate`, `atp keygen`, `atp principal keygen`.

Frozen `--json` output shapes (golden files in `tests/compat/1.0/cli-json/`):

| Command | Golden file |
|---|---|
| `atp trace list --json` | `trace-list.json` |
| `atp policy explain TRACE --json` | `policy-explain.json` |
| `atp test SUITE --json FILE` (the report written to FILE) | `test.json` |
| `atp policy impact --from A --to B --json` | `policy-impact.json` |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Pass: the command did what was asked and nothing it checks failed |
| 1 | The command's own check failed, and only for the commands listed below (`atp test`: a case's decision changed; `atp policy impact --fail-on-widen`: a DENY-to-ALLOW widening; `atp mutate`: an unexpected decision; `atp evidence verify`: the bundle does not verify). Every other command, and `atp policy impact` without `--fail-on-widen`, never exits 1 |
| 2 | Usage or configuration error: bad arguments, a missing or invalid file, an unknown policy set |

Per command, as tested in `tests/compat/test_compat.py` (this list governs):

- `atp test`: 0 when every case matches; 1 when any case's decision changed;
  2 on a usage or config error.
- `atp policy impact`: a report. 0 even when decisions change, unless
  `--fail-on-widen` is given: then 1 if any case goes from DENY to ALLOW.
  Narrowing (ALLOW to DENY) never exits 1. 2 on a usage or config error.
- `atp migrate` (and `atp regression migrate`): 0 when every file is current
  afterwards; 2 when any file is missing, of an unknown kind, unparsable, of an
  unsupported version, or could not be rewritten safely. It never exits 1:
  migrating does not decide anything.
- `atp mutate` exits 1 on an unexpected decision; `atp evidence verify` exits 1
  when the bundle does not verify. `130` on Ctrl-C.

## Private (not covered)

Everything else, including:

- every Python import path, class, function and signature (`atp_core`,
  `atp_gateway`, `atp_policy`, ... are implementation, not a library API);
- the SQLite schema of `atp.db`, and the layout of `.atp/` (`keys.env`,
  `keys/`, `principals/`), which the code migrates itself;
- the execution grant token's content and signing format (`atp-grant/2`), and
  key ids;
- human-readable CLI output (text tables, messages, warnings, stderr), the
  output of `atp doctor` and `atp demo`, and log lines;
- HTTP endpoints not named above (`/traces` listing, `/replay`, `/policy-sets`,
  `/vendors`, `/ledger/payments`, `/health`, `/evals/*`, credential endpoints,
  `/traces/{id}/events`, `/traces/{id}/shadow-outcome`), the HTTP 422 body
  beyond `error` and `fields`, and status codes other than 200/201/4xx classes;
- the built-in `payments-v*` policy sets' contents, the dashboard, the
  benchmark (`bench/`) and its result files.

See also [docs/regression/schema-versioning.md](regression/schema-versioning.md)
for the version fields and migration rules.
