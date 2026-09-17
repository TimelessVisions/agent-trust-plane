## What

## Why

## Security implication
<!-- none / describe which property in docs/design-principles.md is affected and how it is still upheld -->

## Checklist
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest`
- [ ] `uv run python -m atp_evals` still 8/8
- [ ] `uv run atp test examples/regression-suite/accounts-payable.yaml`
- [ ] tests added for any new control or bypass fixed
- [ ] CHANGELOG.md updated
