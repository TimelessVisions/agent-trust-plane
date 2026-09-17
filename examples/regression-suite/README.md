# Sample regression suite

`accounts-payable.yaml` pins eight authorization decisions for the demo
accounts-payable agent. Run it:

```bash
uv run atp test examples/regression-suite/accounts-payable.yaml
uv run atp test examples/regression-suite/accounts-payable.yaml --policy-set payments-v1   # fails on purpose
uv run atp test examples/regression-suite/accounts-payable.yaml --junit results.xml --json results.json
```

Exit code 0 when every pinned decision reproduces, 1 when any changed, 2 when
the suite file is invalid. Runs are decision-only: an ephemeral in-process
gateway answers `/authorize`; nothing is executed and no side effects occur.

`.github/workflows/agent-security-tests.yml` is a copy-paste GitHub Actions
job for a repository that keeps its suites under `security/`. It needs no
secrets and no paid services.
