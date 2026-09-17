# GitHub Action (composite, unpublished)

`action.yml` runs every regression suite with `atp test` and fails the job
if any pinned authorization decision changed. It is a composite action to
copy into your repository; it is deliberately **not** published to the
Marketplace (see `docs/release/releasing.md`).

```yaml
jobs:
  agent-security:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with: { persist-credentials: false }
      - uses: ./.github/actions/atp-test
        with:
          suites: "security/*.yaml"
          source: "git+https://github.com/<owner>/agent-trust-plane@<reviewed-tag>"
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        if: always()
        with: { name: atp-results, path: atp-results-*.xml }
```

What it does not do: comment on PRs (that would need `pull-requests: write`;
read the JUnit/JSON artifacts instead, or use your CI's test reporter),
execute tools, or need secrets.
