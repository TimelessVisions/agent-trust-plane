# Demos — exact reproduction

All four run with `uv sync` done (or via `uv run`, which syncs), no API keys,
no Docker, no services. A/B use the deterministic `SimulatedAgent`; C/D drive
a real MCP client session over stdio; money only ever moves in a local
SQLite table.

## Demo D — wrap (the loop in one command; the README transcript)

```bash
uv run atp demo wrap                 # temp dir; --out DIR to keep the files
```

What happens: `atp mcp init` discovers the notes server's four tools (two
annotated read-only, one destructive) and writes `atp-mcp.yaml` plus
`.atp/policies.yaml`; `atp mcp wrap` starts in a subprocess (proxy + gateway
in one process, upstream as its child); the demo's MCP client calls
`write_note` (ALLOW, executed) and `delete_note` (DENY
`CAPABILITY_NOT_GRANTED`: `notes:destroy` is proposed but not delegated —
the note still exists); then `atp policy explain`, `atp regression add` and
`atp test` run as real subprocesses against the same `.atp/`. Exit code is
the test's (0). The transcript in `docs/demo/wrap-transcript.txt` is a
recording of this run (`scripts/record_demo.py`).

## Demo A — injection (blocked before execution)

```bash
uv run atp demo injection
```

What happens: the accounts-payable agent records the task and the invoice
(untrusted, hashed), follows the injected instruction, proposes a $12,500
payment to `acct-offshore-9931`; the gateway resolves the chain (limit
$1,000), denies with `PAYMENT_EXCEEDS_DELEGATED_AUTHORITY`, issues no grant,
blocks the agent's `/execute` attempt with `GRANT_MISSING`. The command
prints the decision block, the 8-event trace and the ledger row count (0).

Exit code 0.

## Demo B — policy regression (before → change → after → CI)

```bash
uv run atp demo regression                       # writes a suite to a temp dir
uv run atp demo regression --out security/ap.yaml
```

What happens:

1. **Before** — the same agent, under `payments-v1`, proposes $640 to the
   attacker account. Under the limit, so `ALLOW`; it executes; one ledger row.
2. **Change** — the diff between `payments-v1` and `payments-v2` is printed
   (`+ payments.currency.v1`, `+ payments.vendor.approved_destination.v1`).
3. **After** — the *recorded* action is replayed under `payments-v2`:
   `DENY PAYMENT_DESTINATION_RESOURCE_MISMATCH`. The ledger still has one
   row: replay re-evaluates, it cannot undo, and it does not rerun the agent.
4. **Pin** — the trace is converted to a regression case with the hardened
   expectation and written to a suite file.
5. **Run** — the suite is run under both policy sets: v1 fails (0/1,
   "responsible: no policy matched under payments-v1"), v2 passes (1/1).

Exit code 0 only if v2 passes and v1 fails. Then put the suite in CI with
`uv run atp test <suite> --junit results.xml`.

## Demo C — real MCP integration

```bash
uv run atp demo mcp
```

What happens: an ephemeral gateway starts on a free loopback port; the
operator issues a credential for `notes-assistant` and a delegation
(`notes:read`, `notes:write` over `note:*`, no `notes:delete`); a proxy config
is written; the demo acts as an MCP client and launches `atp mcp-proxy` over
stdio, which launches the notes MCP server over stdio.

- `tools/list` → `list_notes, read_note, write_note` (unmapped `delete_note`
  hidden)
- `write_note` → ALLOW, forwarded, `todo.txt` exists on disk
- `read_note` → ALLOW, returns the text
- `delete_note` → DENY `CAPABILITY_NOT_GRANTED`, the file still exists
- the gateway's traces for all three calls are listed

Exit code 0. The config and notes directory are left in a temp folder
(printed) so you can reuse them with `atp mcp-proxy`.

To try a third-party server: `ATP_E2E_NPX=1 uv run pytest adapters/mcp/tests/test_proxy_third_party.py`
(needs Node/npx; downloads `@modelcontextprotocol/server-filesystem`).

## Dashboard

```bash
uv run atp keygen --write .env && uv run atp serve
cd apps/dashboard && npm install && npm run dev      # http://localhost:3000
```

Paste `ATP_OPERATOR_KEY` from `.env` into the key field, click **Run eval
suite**, then select EVAL-006 (selected by default after a run) to see the
before/after panel. The screenshot in the README was captured this way.
