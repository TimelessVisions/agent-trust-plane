# First-user test v2 (2026-09-17)

A scripted simulation of someone who knows nothing about ATP, following
README.md literally, in a fresh clone with a **cold uv cache** (fresh
`UV_CACHE_DIR`), no `.env`, no `ATP_*` variables, on the maintainer's
machine (Windows 11, Python 3.14.6 via uv, Node 24.18, uv 0.9.x, warm OS
file cache, wired network). Two runs; every command and its exit code was
recorded by the script (`scratchpad/first_user.py`, not in the repo; the
JSON log is summarised here).

## Timings

| Step | Run 1 (s) | Run 2 (s) | Exit |
|---|---:|---:|---|
| `git clone` (local source) | 1.2 | 1.1 | 0 |
| `uv run atp demo wrap` — cold cache: resolves + installs 70 packages, builds the workspace, runs the whole loop | **36.5** | 35.0 | 0 |
| `uv run atp doctor` | 3.2 | 3.2 | 0 |
| `uv run atp mcp init --name fs -- npx -y @modelcontextprotocol/server-filesystem <sandbox>` (npx fetch included) | 14.1 | 7.2 | 0 |
| (edit `atp-mcp.yaml`, see finding 1) | — | 0 | — |
| `atp mcp wrap` driven by a 20-line MCP client: `write_file` in sandbox, `write_file` to `../escape.txt`, `move_file` | 10.0 | 10.1 | 0 |
| `uv run atp trace list` | 1.4 | 1.4 | 0 |
| `uv run atp policy explain <trace>` | — | 1.4 | 0 |
| `uv run atp regression add <trace> --name "traversal stays denied"` | — | 1.6 | 0 |
| `uv run atp test atp-regression.yaml` | — | 1.8 | 0 |
| `uv run atp mutate <trace>` | — | 1.8 | 0 |
| **Total, clone to a passing regression test** | | **64.6** | |

Time to first useful result (an ALLOW and a DENY on a real MCP server):
**~37 s cold**, of which ~30 s is `uv sync` downloading dependencies.

## What the second run showed (the loop on the reference filesystem server)

- `write_file` inside the sandbox → `ALLOW`, executed (`moved.txt` exists
  afterwards because `move_file` was also allowed inside the sandbox).
- `write_file` to `<sandbox>/../escape.txt` → `DENY RESOURCE_OUT_OF_SCOPE`
  by `resource.scope.v1`; the resource was normalised to
  `path:c:/…/escape.txt` and compared with `path:c:/…/sandbox/*`; the file
  does not exist afterwards.
- `atp policy explain` named the failing constraint with both values and
  the grant to widen.
- `atp regression add` produced a suite pinned to `fs-v1` with
  `policies: .atp/policies.yaml`; `atp test` passed 1/1.
- `atp mutate` on the denied trace: 11 mutations, 11 denied, 0 unexpected.

## Findings (every failure, in order)

1. **The first write was denied.** Run 1: `write_file`, `edit_file` and
   `move_file` are marked `destructiveHint` by the reference server, so
   `atp mcp init` mapped them to `fs:destroy` and did *not* delegate it.
   The generated file's header says exactly that, and the denial message
   names the missing capability; a one-line edit (`- fs:destroy` under
   `authority.capabilities`) fixed it. Kept as the default (fail closed on
   what the server itself flags destructive) and now stated in the README
   and in the init output. A user who does not read the header will hit
   this.
2. **`trace list` truncates long resources** (31 chars) so two Windows temp
   paths looked identical. Cosmetic; `--json` has the full value. Left
   as is; widened columns would wrap on 80-column terminals.
3. **`atp mutate` on a DENY case is uninformative** (everything stays
   denied). The README example mutates an allowed action; the CLI could
   say "original decision is DENY; mutations of an ALLOW are more useful".
   Not changed.
4. Nothing needed an API key, Docker, a database, or a copied secret.
   `.atp/keys.env` was generated and gitignored automatically.

## Not covered

Linux/macOS (no machine in this pass); an IDE client (Claude Desktop,
Cursor) launching `atp mcp wrap` — the script used the MCP Python SDK's
`stdio_client`, which is what those clients do, but that is inference and
the compatibility matrix marks them *not verified*.
