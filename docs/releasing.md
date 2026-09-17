# Release process

Versions are `0.x` while the API is unstable; breaking changes may land in a
minor bump and are listed under "Changed" in CHANGELOG.md.

1. Run every check: `scripts/check.sh` (or `.ps1`), plus
   `uv run python benchmarks/authz_overhead.py --n 300 --out docs/benchmarks.md`
   if anything on the hot path changed.
2. Move CHANGELOG "Unreleased" into a dated version section.
3. Bump `version` in every `pyproject.toml` (root, packages/*, services/*,
   adapters/*, examples/*) and `apps/dashboard/package.json`.
4. Commit, tag `vX.Y.Z`, push tag.
5. Create a GitHub release from `docs/release-notes-vX.Y.Z.md`.
6. Packages are not on PyPI yet; consumers install from the tag
   (`uv tool install "git+…@vX.Y.Z#subdirectory=packages/cli"`). Publishing to
   PyPI needs trusted publishing configured and a maintainer decision.

Do not publish a GitHub Action from this repository until its security and
maintenance requirements (pinned dependencies, no secrets, review of
third-party actions) have been reviewed and documented.
