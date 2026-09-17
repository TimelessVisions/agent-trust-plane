# Good first issues (candidates)

Scoped, testable, each visible to a developer using the tool. File them as
issues once the repository is public; each names the files to touch.

1. **`TraceStore` export wrapper** — a store that forwards every `append` to a
   sink (start with a JSONL file), so events can be shipped to WORM storage.
   `packages/audit/src/atp_audit/store.py`; test with the existing tamper
   tests. (docs: `docs/security/trace-integrity.md`)
2. **`atp doctor --json`** for CI consumption. `packages/cli/src/atp_cli/doctor.py`.
3. **JSON Schemas for `atp-mcp.yaml`, `policies.yaml` and suites** generated
   from the pydantic models into `docs/schemas/`, with a test that they are
   up to date. (`model_json_schema()`)
4. **Absolute `expires_at` in suites** so "expired delegation" cases can be
   pinned. `packages/evals/src/atp_evals/regression/format.py`, `runner.py`.
5. **Custom 422 handler** that strips the echoed `input` from validation
   errors (security review O9). `services/gateway/src/atp_gateway/app.py`.
6. **Idempotency-key injection option on `ToolMapping`** (`idempotency_argument:
   name` → the proxy adds `grant_id` under that name before forwarding, and
   the hash covers it). `adapters/mcp/src/atp_adapter_mcp/`, e2e test.
7. **Second example upstream**: a read-only SQLite query server whose resource
   is built from two arguments (`db:{database}/{table}`). `examples/`.
8. **Windows path fixture for the filesystem server test** (case folding,
   drive letters) in `adapters/mcp/tests/test_proxy_third_party.py`.
9. **`atp policy coverage --json` consumers**: a tiny script that fails CI when
   a newly recorded action has an unguarded argument. `examples/`.
10. **Mutation strategy for list arguments** (append/remove an element) in
    `packages/evals/src/atp_evals/analysis.py`, with tests.
11. **OpenTelemetry exporter (optional extra)** emitting one `execute_tool`
    span per decision from a `TraceStore` wrapper; conventions are in
    Development status, so mark it experimental.
12. **Streamable HTTP served by the proxy** behind a bearer token — larger;
    start with a design note in `docs/integrations/`.
