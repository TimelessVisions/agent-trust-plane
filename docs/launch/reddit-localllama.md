# r/LocalLLaMA (draft — not published)

Title: Open-source: put an authorization boundary in front of your MCP servers and turn denied tool calls into regression tests (no cloud, no API keys)

Body:

If you run local agents with MCP tools, the scary part is not the model,
it is `write_file` / `move_file` / `send_payment` with arguments the model
was tricked into. I wrote a local-first tool for that: `atp mcp init -- npx
-y @modelcontextprotocol/server-filesystem ./sandbox` then `atp mcp wrap`
serves a protected copy over stdio; every call is decided against a
delegation you control (paths scoped to the sandbox, `..` normalised,
destructive tools denied unless you delegate them), and denied calls never
reach the server. Everything is recorded in `.atp/` on your disk; `atp
policy explain` says why; `atp regression add` pins it as a test.

Runs entirely locally: Python + uv, SQLite, nothing else. There is a shadow
mode that only records what *would* be denied. Verified against the
reference filesystem server; other clients/servers are listed as not
verified until someone tries them. Not a gateway, not audited, no users
yet — feedback on real servers is what I need.
