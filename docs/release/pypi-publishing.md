# Publishing to PyPI (runbook)

Status (2026-09-17): **nothing has been published to PyPI or TestPyPI**. The
name `agent-trust-plane` is unregistered. This runbook describes the path
that has been prepared and tested up to the point of upload; every step
that touches PyPI needs the maintainer's explicit action.

PyPI releases are effectively immutable: a version can be yanked but never
replaced. A broken `X.Y.Z` on PyPI means shipping `X.Y.Z+1`, never
re-uploading. The same rule already applies to our Git tags and GitHub
Releases, so all three (tag, GitHub Release, PyPI version) must refer to the
same source commit.

## Why v0.3.1 is not the first PyPI version

The `v0.3.1` tag and GitHub Release are final and correct, but the
artifacts built from that commit would present badly on PyPI: the README
has ~30 relative links and a relative hero image (broken on pypi.org, which
does not resolve repository-relative URLs), and the metadata has no project
URLs, keywords or classifiers, so the PyPI page would not even link back to
the repository. Fixing that requires new artifacts, i.e. a new version.
`main` now carries the fixes (absolute README links, `[project.urls]`,
keywords, accurate classifiers, a second console script so
`uvx agent-trust-plane …` works). The first PyPI version will be **v0.3.2**
built from a tag that includes them.

## Prerequisites

- A PyPI account owned by the maintainer, with 2FA (required by PyPI for
  publishing).
- The GitHub repository `TimelessVisions/agent-trust-plane` (public) with
  the workflow `.github/workflows/publish.yml` on the tagged commit.
- A GitHub Actions **environment** named `pypi` on the repository
  (Settings → Environments → New environment), with required reviewers
  (the maintainer) and, optionally, a deployment branch/tag rule limited
  to tags `v*`. Create it before the first Release (see below).
- A tag ruleset protecting `v*` tags from update and deletion (see below).

## Trusted Publishing setup (OIDC, no long-lived token) — manual, maintainer only

Per https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
(checked 2026-09-17), a *pending publisher* can be registered before the
project exists; the first successful publish creates the project and
converts it to a normal publisher. A pending publisher does **not** reserve
the name — if someone registers `agent-trust-plane` first, the pending
publisher is invalidated; do not leave a long gap between registering and
publishing.

On https://pypi.org/manage/account/publishing/ add a pending publisher with
exactly:

| Field | Value |
|---|---|
| PyPI project name | `agent-trust-plane` |
| Owner | `TimelessVisions` |
| Repository name | `agent-trust-plane` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Nothing else is needed on the PyPI side. No API token is created; no
secret is stored in GitHub.

## The release workflow (`.github/workflows/publish.yml`)

Triggers: **only** `release: published` (a GitHub Release the maintainer
publishes) or a manual `workflow_dispatch` with a tag name. Never `push`
or `pull_request`.

Jobs:

1. `build` — validates the tag name against `^v[0-9]+\.[0-9]+\.[0-9]+$`
   (the tag reaches the shell only through `env`, never by `${{ }}`
   interpolation); refuses releases marked pre-release or draft; checks
   out `refs/tags/<tag>` and, for release events, refuses unless the
   checked-out commit is the commit the release was published against
   (`github.sha`); refuses unless `v` + `pyproject.toml` version == tag;
   `uv build` with the pinned build backend; `twine check --strict`;
   `scripts/check_dist.py` (exactly one wheel and one sdist named for the
   version; Name/Version/License-Expression MIT/License-File/
   Requires-Python/Project-URL/Keywords/Classifier present; the eleven
   intended packages and nothing else; `py.typed` everywhere; no `.env`,
   `keys.env`, `.db`, `.atp/`, tests, caches, git metadata; no
   secret-shaped strings or local paths; no non-index `Requires-Dist`; no
   relative links in the long description); installs the wheel in an
   isolated `uvx` environment and runs `agent-trust-plane --help`,
   `atp doctor` and `agent-trust-plane demo injection`; records
   `sha256sum` of the artifacts as a job output; uploads them as a
   workflow artifact.
2. `publish` — environment `pypi`; permissions `contents: read`,
   `id-token: write` (the only elevated permission, job-scoped); downloads
   the artifact, refuses unless it holds exactly the two files with the
   digests the build job recorded, then
   `pypa/gh-action-pypi-publish` pinned to the commit of v1.14.2
   (`dc37677b…`). With Trusted Publishing the action generates and uploads
   PEP 740 digital attestations by default (`attestations: true`), signed
   via Sigstore against the workflow identity — no extra configuration and
   no custom cryptography.
3. `verify` — `uvx --isolated --no-cache agent-trust-plane==<version>
   --help` from PyPI, with retries while the index propagates.

All third-party actions are pinned to commit SHAs; the workflow has
`permissions: contents: read` at the top level and on every job. Every
job has a timeout. `scripts/check_dist.py` also runs in the `package` job
of the ordinary CI workflow on every push, so the gate is exercised long
before a release.

Two GitHub-side settings matter for the gates to mean anything:

- Create the `pypi` environment **before** publishing the first Release.
  A workflow that references an environment that does not exist creates
  it automatically with no protection rules, i.e. no required reviewer.
- Add a tag ruleset (Settings → Rules → Rulesets → New tag ruleset,
  target `v*`) that blocks updating and deleting tags. Without it anyone
  with write access can move a `vX.Y.Z` tag; the workflow's
  released-commit check catches a move between publish and checkout, not
  a move before the Release is created.

## Release procedure (for v0.3.2 and later)

1. On `main`: bump the version in the root `pyproject.toml`, every
   workspace `pyproject.toml`, `apps/dashboard/package.json` (and the two
   root entries of `package-lock.json`), `atp_gateway/app.py`,
   `atp_adapter_mcp/proxy.py`, README/SECURITY status lines; add the
   CHANGELOG section and `docs/release/vX.Y.Z-notes.md`; `uv lock` +
   `uv sync` (lockfile member versions); run `scripts/check.sh`.
2. Commit `release: prepare vX.Y.Z`; push `main`; wait for `ci` to be
   green on that exact commit (five jobs).
3. Tag that commit: `git tag -a vX.Y.Z -m "Agent Trust Plane vX.Y.Z"`;
   push only the tag.
4. Build locally from a clean export of the tag (`git archive vX.Y.Z`),
   run `python scripts/check_dist.py dist`, record the sha256 of the wheel
   and sdist (builds are byte-for-byte reproducible: hatchling normalises
   archive timestamps and the backend version is pinned).
5. Create the GitHub Release for the tag with the curated notes and the
   two artifacts.
6. **Publishing** happens when that Release is published: the `publish`
   workflow runs, the `pypi` environment asks the maintainer to approve
   the deployment, and the action uploads with OIDC. Compare the hashes it
   prints (`print-hash: true`) with step 4.
7. Compare the digests the `publish` job verified with step 4.
   Post-publication smoke tests (also run by the `verify` job):
   `uvx agent-trust-plane --help`, `uvx agent-trust-plane demo mcp`,
   `pip install agent-trust-plane` in a fresh venv then `atp doctor`.
8. Update README/docs that say "not on PyPI" and the compatibility matrix
   row "PyPI: NOT PUBLISHED" in a normal follow-up commit.

## Rollback reality

- A bad upload cannot be replaced. Options: yank the version on PyPI
  (installs by exact pin still work; resolvers skip it) and publish the
  next patch version.
- A wrong Trusted Publisher configuration fails closed (upload rejected);
  fix the publisher, re-run the workflow for the same tag.
- Never re-tag: if the tagged source is wrong, the next version gets a new
  tag and a new GitHub Release.

## Checks performed before this runbook was written (2026-09-17)

Recorded in `docs/release/verification.md` (PyPI readiness section):
name availability, reproducible rebuild of v0.3.1 matching the GitHub
Release assets byte-for-byte, wheel/sdist content scan, install matrix on
Python 3.12/3.13/3.14, `uvx`/`pipx` smoke tests, Linux dependency license
table, pip-audit, `twine check`.
