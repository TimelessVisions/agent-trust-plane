# 60-second technical demo (script)

For a senior engineer. Every line is a real command with real output; no
narration claims anything the terminal does not show. Prepare once:
`uv run atp mcp init --name fs -- npx -y @modelcontextprotocol/server-filesystem /abs/sandbox`
(then edit `.atp/policies.yaml` to add the rule in step 4). Run with the
MCP client of your choice pointed at `atp mcp wrap`; the transcript below
uses the notes server so it needs nothing but this repository.

| t | on screen | say |
|---|---|---|
| 0–10 s | `uv run atp demo wrap` → `tools/list`, `write_note -> ALLOW … file exists: True`, `delete_note -> DENY CAPABILITY_NOT_GRANTED … note still exists: True` | "A real MCP server behind the proxy. Write allowed and executed; delete denied before it reached the server. The gateway ran in-process; nothing was configured by hand." |
| 10–20 s | `uv run atp trace show <trace>` | "Eight hash-chained events: proposal, resolved delegation, every policy result, the decision. No grant was minted, so nothing could execute." |
| 20–30 s | `uv run atp policy explain <trace>` | "Who asked, on whose authority, the chain human → agent, the constraint that failed with both values, and what would need to change — derived from the record, not generated." |
| 30–40 s | `uv run atp policy coverage` | "The same tool has an unguarded argument: `text` length. That is the hole." |
| 40–50 s | add `argument_max_length` rule to `.atp/policies.yaml` as `fs-v2`; `uv run atp policy impact --from notes-v1 --to notes-v2` | "Impact re-decides every recorded action under both versions: one ALLOW → DENY, nothing widened." |
| 50–60 s | `uv run atp regression add <trace> && uv run atp test atp-regression.yaml` → `1/1 passed`, then `--policy-set notes-v1` → exit 1 | "Pinned. CI fails if this decision ever flips. Authorize-only; a spy on execute sees zero calls." |

Closing line: "Everything you saw is in `.atp/` and one YAML file; the
boundary only holds if the agent cannot reach the server without the proxy —
that is a deployment property, documented, not a claim."
