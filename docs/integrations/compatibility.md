# Compatibility matrix

Only rows marked **VERIFIED** were exercised by a test or a manual run in
the maintainer environment on the date given. Nothing here is inferred.
Environment: Windows 11, Python 3.14.6, MCP Python SDK 2.2.0, Node 24.18.

| Component | Status | How verified | Date |
|---|---|---|---|
| MCP stdio (proxy served to a client) | VERIFIED | proxy e2e, wrap e2e, demo (three processes) | 2026-09-17 |
| MCP stdio upstream (proxy → server) | VERIFIED | proxy e2e, wrap e2e | 2026-09-17 |
| MCP Streamable HTTP upstream (proxy → server) | VERIFIED | `test_proxy_http_upstream.py` against the notes server served by uvicorn | 2026-09-17 |
| MCP Streamable HTTP served by the proxy | NOT SUPPORTED | — | — |
| Legacy HTTP+SSE upstream | NOT SUPPORTED (deprecated in the spec) | — | — |
| `initialize`, `tools/list`, `tools/call` | VERIFIED | e2e tests | 2026-09-17 |
| `input_required` / task-style tool results | NOT SUPPORTED (refused, recorded) | proxy code path | — |
| prompts, resources, notifications, cancellation | NOT PROXIED | — | — |
| MCP protocol revision negotiated by the SDK | VERIFIED 2025-11-25 (client default) with the 2.2.0 SDK | e2e initialize | 2026-09-17 |
| In-repo notes MCP server (Python) | VERIFIED | CI | 2026-09-17 |
| `@modelcontextprotocol/server-filesystem` (Node, stdio) | VERIFIED (opt-in `ATP_E2E_NPX=1`) | `test_proxy_third_party.py` passed today | 2026-09-17 |
| Other third-party MCP servers | NOT VERIFIED | — | — |
| Claude Desktop | NOT VERIFIED | not tested; the proxy is a plain stdio server, but no run was made | — |
| Claude Code | NOT VERIFIED | — | — |
| Cursor | NOT VERIFIED | — | — |
| VS Code / Copilot MCP | NOT VERIFIED | — | — |
| OpenAI Agents SDK | NOT VERIFIED; decision-only hook documented | `frameworks.md` | — |
| LangGraph / CrewAI / AutoGen | NOT VERIFIED | `frameworks.md` | — |
| A2A | NOT SUPPORTED (design note) | `../research/agent-to-agent-future.md` | — |
| Python 3.12 / 3.13 (ubuntu-latest) | VERIFIED: lint, mypy, full pytest, evals, doctor, demos A–D, sample suite, impact, link check | GitHub Actions [run 35234834560](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/35234834560) at commit `a4ac997` | 2026-09-17 |
| Python 3.14 | VERIFIED locally | full suite | 2026-09-17 |
| Windows 11 | VERIFIED (maintainer environment) | full suite, demos, clean install | 2026-09-17 |
| Linux (ubuntu-latest) | VERIFIED (same job set as above, incl. the stdio + Streamable HTTP MCP e2e tests and `atp demo wrap`) | [run 35234834560](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/35234834560) | 2026-09-17 |
| Windows (windows-latest, Python 3.13) | VERIFIED (same job set) | [run 35234834560](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/35234834560) | 2026-09-17 |
| macOS | NOT VERIFIED (not in the CI matrix) | — | — |
| Wheel build + isolated `uvx` run + pip-audit + SBOM (`package` job) | VERIFIED | [run 35234834560](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/35234834560) | 2026-09-17 |
| Dashboard typecheck + production build (`dashboard` job, Node 22) | VERIFIED | [run 35234834560](https://github.com/TimelessVisions/agent-trust-plane/actions/runs/35234834560) | 2026-09-17 |
| `uvx --from <wheel> atp` | VERIFIED | `docs/release/verification.md` | 2026-09-17 |
| `pipx install <wheel>` | see `docs/release/verification.md` | — | 2026-09-17 |
| PyPI | NOT PUBLISHED | — | — |

Adding a row requires a test or a documented manual run with its date.
