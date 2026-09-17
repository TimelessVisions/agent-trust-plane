# Good first issues (candidates)

Scoped, testable, and each improves something a developer would notice.
File them as issues once the repository is public.

1. **`atp test --diff <other-policy-set>`** — run a suite under two policy
   sets and print only the decisions that differ. (`packages/evals/regression`)
2. **`expires_at` support in suites** — allow absolute expiry so "expired
   delegation" cases can be pinned. (`format.py`, `runner.py`)
3. **`atp mcp-init --from-upstream`** — launch the upstream once, list its
   tools, and emit a mapping skeleton with every tool commented out.
4. **Dashboard: filter traces by agent id** — the trace list grows quickly
   after evals. (`apps/dashboard/components/TraceList.tsx`)
5. **JSON Schema for `atp-mcp.yaml` and suite files** — generated from the
   pydantic models, published under `docs/schemas/`, referenced from the docs.
6. **`atp doctor --json`** for CI consumption.
7. **Custom 422 handler** that strips the echoed `input` from validation
   errors (security-review O9).
8. **Windows PowerShell version of `scripts/demo.sh`.**
9. **Proxy: `--dry-run` flag** that authorizes but never forwards, printing
   decisions — useful for mapping a new upstream.
10. **A second example upstream** (e.g. a read-only SQLite query server) to
    show a `resource_template` built from two arguments.
