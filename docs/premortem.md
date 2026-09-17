# Pre-mortem — September 2027, Agent Trust Plane failed

Assume the project has few users, no contributors, no deployments and no
mindshare. For each failure mode: root cause → earliest warning signal →
measurable indicator → prevention → mitigations (architecture / product /
docs) → validation test. Items marked **[acted on]** changed the v0.3.0
plan; the change is named.

Format per item: **Cause.** **Signal.** **Indicator.** **Prevent.**
**Arch / Product / Docs.** **Test.**

1. **Nobody understands what ATP does.** Cause: three product nouns
   (gateway, policy, evals) in one README. Signal: first-issue titles
   asking "is this a gateway?". Indicator: README bounce; questions
   repeating the same confusion. Prevent: one sentence, one loop, one
   demo. Arch: n/a. Product: README opens with allow/deny/regression in
   ten lines. Docs: `why-atp.md`, ADR-0003. Test: five people describe it
   back in one sentence (post-launch experiment 3). **[acted on: README
   rewritten around the loop]**
2. **"Yet another MCP gateway."** Cause: the proxy is the visible surface.
   Signal: comparisons to agentgateway in comments. Indicator: issues
   asking for transports/federation. Prevent: say "sits beside gateways"
   in the first screen; ship the interceptor story. Docs: `why-atp.md`,
   feature matrix. Test: the matrix shows an empty operational column
   and a full decision column. **[acted on]**
3. **"Yet another policy engine."** Cause: a YAML policy format invites
   the comparison. Signal: "why not Cedar?" Indicator: policy-language
   feature requests. Prevent: keep the format tiny; document the policy
   boundary for OPA/Cedar adapters. Docs: `why-not-just-opa.md`. Test:
   the policy YAML has ≤ 8 rule kinds and the doc says so. **[acted on:
   rule kinds capped; adapter boundary documented]**
4. **Install too complicated.** Cause: eleven-package workspace, clone
   required. Signal: quickstart issues. Indicator: time-to-first-decision
   > 5 min. Prevent: single wheel, `uvx`. Product: `atp doctor`. Test:
   `docs/first-user-test-v2.md` measured run. **[acted on: single
   distribution built and installed via uvx]**
5. **Demo impressive, problem unreal.** Cause: finance demo is synthetic.
   Signal: "cool, but I do not have a payments agent". Indicator: no one
   wraps their own server. Prevent: `atp mcp wrap` on *their* server in
   one command. Test: the wrap flow against the reference filesystem
   server is a CI test. **[acted on]**
6. **MCP support too narrow.** Cause: stdio only, one upstream. Signal:
   "does it work with my remote server?" Indicator: Streamable HTTP
   requests. Prevent: upstream Streamable HTTP now; served Streamable HTTP
   with auth next. Docs: compatibility matrix with VERIFIED only. Test:
   HTTP upstream e2e test. **[acted on: upstream HTTP]**
7. **Framework integration requires rewriting the agent.** Cause: only the
   HTTP client existed. Signal: "how do I use this with LangGraph?".
   Prevent: the proxy path needs zero agent changes; say so first. Docs:
   integrations page listing decision-only hooks honestly. Test: proxy
   e2e with an unmodified third-party server. **[acted on: positioning]**
8. **Policy system weaker than OPA/Cedar.** Cause: true. Signal: "can I
   write X?" Prevent: do not compete; expose the boundary. Docs:
   `why-not-just-opa.md`. Test: `Policy` ABC has no engine-specific
   imports; an adapter design exists.
9. **Guarantees depend on deployment assumptions users miss.** Cause:
   bypass is documented but buried. Signal: "I called the tool directly
   and nothing stopped it". Prevent: `enforcing-the-boundary.md` linked
   from README security section; `atp doctor` warns when upstream is
   network-reachable (future). Test: `test_direct_upstream_access_is_not_protected`
   exists and is cited. **[acted on: doc]**
10. **Proxy can be bypassed.** Same as 9; architectural mitigation is
    gateway-owned upstream credentials (Phase 23) — designed, demo not
    built; stated as a gap.
11. **Tool credentials not isolated.** Cause: the proxy launches the
    upstream with whatever env the user gives. Prevent: document that
    upstream env belongs in the proxy config, never in the agent host;
    future: credential vault held by the proxy. Test: config loader never
    exports upstream env to the client side (proxy e2e checks the client
    env is not inherited). Docs: boundary doc.
12. **Agent identity is weak.** Cause: bearer tokens. Signal: security
    reviewers. Prevent: `IdentityProvider` interface with the bearer
    provider as one implementation; document DPoP/SPIFFE path. Test:
    provider interface has a second (test) implementation. **[acted on:
    interface]**
13. **Replay misunderstood as agent rerun.** Cause: the word "replay".
    Prevent: every replay output says "decision only; nothing executed";
    the first-principles doc defines the five kinds. Test:
    `test_replay_never_executes` and the property test. **[acted on]**
14. **Imported traces become an attack surface.** Cause: `atp regression
    add` reads traces. Prevent: strict models, size caps, no execution
    during conversion; evidence bundles carry hashes. Test: hostile-trace
    tests (existing) + bundle tamper test. **[acted on]**
15. **Regression testing too cumbersome for CI.** Cause: `record` needed
    a live gateway and operator key. Prevent: `atp regression add TRACE`
    reads the local store. Test: CLI test from a wrapped session to a
    passing suite in two commands. **[acted on]**
16. **Cannot understand why a decision occurred.** Prevent: `atp policy
    explain` prints every evaluation and the deterministic "what would
    need to change". Test: explain output for the $12,500 case names
    limit, source grant and required change. **[acted on]**
17. **Overhead unacceptable.** Cause: ~21 ms per MCP call via HTTP.
    Prevent: in-process mode for `mcp wrap` (no HTTP hop); benchmark
    published with limits. Test: benchmark harness runs in CI (not
    gated). **[acted on: in-process wrap]**
18. **Dashboard becomes a distraction.** Prevent: freeze dashboard scope
    to trace/decision/authority/before-after; CLI is primary. Docs: ADR-0003
    says so. **[acted on: no new dashboard work]**
19. **Repo huge, core unclear.** Prevent: single distribution; docs IA;
    `DEVELOPMENT.md` with a 10-line module map. **[acted on]**
20. **Too many half-built features.** Prevent: `rejected-ideas.md`;
    every shipped command has tests and a doc. Test: CLI test per
    subcommand.
21. **Documentation exaggerates maturity.** Prevent: "experimental", "no
    users", "not audited" in README; compatibility matrix with VERIFIED
    only. Test: grep for "production-ready" returns nothing. **[acted on]**
22. **Embarrassing vulnerability.** Prevent: red-team doc with attempted
    attacks and tests; SECURITY.md; property tests; hostile review.
    **[acted on: Phase 7 tests]**
23. **Supply-chain weakness.** Prevent: SHA-pinned actions, minimal
    permissions, `pip-audit` in CI, SBOM script. **[acted on]**
24. **CLI collides.** Research: PyPI `atp` and `atp-core` are taken by
    unrelated projects; Debian's `atp` (text→PostScript) was removed.
    Prevent: distribution `agent-trust-plane`, script `atp` kept, collision
    documented; `python -m atp_cli` always works. **[acted on: docs]**
25. **Package naming hurts discovery.** Prevent: one PyPI name matching the
    repo; topics list. **[acted on]**
26. **Contributors cannot understand the architecture.** Prevent:
    `DEVELOPMENT.md`, invariants list, ADRs. **[acted on]**
27. **Issues unanswered.** Prevent: CONTRIBUTING states response
    expectations; issue templates. Signal: median first-response > 7 days.
28. **Depends on one protocol.** Prevent: kernel has no MCP import
    (checked by a test that imports the kernel without `mcp` installed
    — simulated via `sys.modules` block). **[acted on: test]**
29. **MCP changes.** Prevent: adapter isolates SDK; pin `mcp>=2.2,<3`;
    protocol version recorded in traces from the proxy. Test: e2e suite.
30. **Platforms add built-in authorization.** Signal: OpenAI tool
    guardrails, MCP scope SEPs. Prevent: ATP's value is *delegated
    authority + evidence + regression*, which platform hooks do not
    provide; integrate with those hooks rather than compete.
31. **Vendors copy the workflow.** Accept; the open format (suites,
    bundles) and the tests are the moat, not secrecy.
32. **Users need distributed deployment first.** Prevent: say "one
    gateway instance" up front; design stores behind interfaces
    (already). Signal: Postgres requests.
33. **Policy authoring too difficult.** Prevent: YAML sets generated by
    `mcp init` from the server's tool list; explain/impact/coverage tell
    the author what a change does. **[acted on]**
34. **Security likes it, developers hate it.** Prevent: developer loop
    first (wrap → see decision → add regression); no approval prompts in
    the default path. Test: first-user test timings.
35. **Developers like it, security does not trust it.** Prevent: threat
    model with guarantees/assumptions/non-guarantees; property tests;
    state-machine spec. **[acted on]**
36. **No path from demo to infrastructure.** Prevent: `deployment.md` and
    boundary doc; Docker interceptor design; roadmap NOW/NEXT. Signal:
    "how do I run this for real?" issues.
37. **Benchmark criticised.** Prevent: publish methodology, hardware,
    n, percentiles; never claim "faster than". **[acted on: expanded]**
38. **Stars but no retention.** Indicator: no suites committed in other
    repos. Prevent: the regression file is the retention hook; make
    `atp regression add` the default advice on every denial.
39. **Commercial offer damages credibility.** Prevent: keep offers out of
    README; no fake validation; MIT license unchanged.
40. **Competitor has stronger distribution.** Accept; win on the one
    workflow no one else has (record → replay → regression → impact) and
    on honesty.

## Plan changes driven by this pre-mortem

- P0 became: one-command wrap (4, 5, 15), local-first store so regression
  works offline (15), explain (16), impact/diff (33), mutation (33),
  shadow mode declared by the gateway (5, 34), single distribution +
  uvx (4, 19, 25), property tests (22, 35), boundary doc (9, 10, 11).
- Explicitly *not* P0: served Streamable HTTP (6 → NEXT), OTel (P1),
  approval protocol (design only), budgets (design only), framework
  adapters (rejected for this pass), dashboard work (frozen).
