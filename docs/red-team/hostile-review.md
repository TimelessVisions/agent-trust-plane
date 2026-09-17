# "Why Agent Trust Plane Is Just Another Toy MCP Proxy"

*The strongest review a hostile senior engineer could write today, followed
by the only responses that count: code, tests, evidence, and admissions.*

## The review

1. **It is a stdio proxy for one server.** No Streamable HTTP served, no
   auth on its own endpoint, no federation, no isolation, no secrets
   management. agentgateway and ToolHive do all of that with thousands of
   stars and real deployments. This is a weekend project with a threat
   model.

2. **The security boundary is a deployment assumption.** The docs admit an
   agent that launches the server itself bypasses everything. So the
   "authorization boundary" is a line in a config file; the actual
   boundary is whatever network policy you would have written anyway.

3. **The policy language is eight YAML rule kinds.** No expressions, no
   conditions across arguments, no time. Anyone serious will use OPA or
   Cedar, and then what is left?

4. **The "kernel" is a Python service with a threading lock and SQLite.**
   One instance, no HA, symmetric HMAC, an omnipotent operator key on the
   developer's disk. Calling that a trust anchor is generous.

5. **Bearer tokens.** In 2026. A stolen `atpa_…` string is the agent.

6. **"Regression testing" is running YAML through the same engine that
   made the decision.** It tests that the code is deterministic, which it
   would be anyway. It cannot test the agent, the prompt, or the tool.

7. **Mutation testing is a for-loop over `+1`, `x10`, sibling path.** The
   academic prior art mutates policies with constraint solvers; this
   mutates requests with a hand-written list and calls it analysis.

8. **The benchmark says 11 ms overhead, but the "cold" column says the
   first call costs 160–200 ms** and everything is single-threaded on one
   Windows laptop.

9. **Zero users, zero Linux runs, zero clients verified.** The
   compatibility matrix is mostly NOT VERIFIED. The CI has never executed
   on a remote.

10. **The generated config trusts server annotations.** A malicious server
    marks `rm -rf` read-only and the generator hands it `read`.

## The response

**1. Scope.** Correct, and stated in the first screen of the README and in
[ADR-0003](../adr/0003-category-definition.md): this is not a gateway and
does not compete on transports or isolation. What it does that those
gateways do not, with their own issue numbers as evidence: decide on
argument values against delegated limits (agentgateway #2069 open;
ToolHive scalars only; Docker logs argument shape only), bind the decision
to a single-use grant over the exact action, replay a recorded decision,
and turn it into a CI test ([competitive-code-review.md](../research/competitive-code-review.md)).
Streamable HTTP *upstream* is verified over the real protocol
(`test_proxy_http_upstream.py`); serving it with client auth is the next
item on the roadmap, not hidden.

**2. The boundary.** Correct that it is a deployment property, and that is
why `enforcing-the-boundary.md` exists, why the bypass is a *test*
(`test_direct_upstream_access_is_not_protected`), and why the generated
config keeps upstream secrets on the proxy side. Every gateway in the
comparison has the same property; none of them state it. The part ATP adds
on top of network policy is what happens *inside* the mediated path:
argument-aware decisions, exactness, evidence, replay. Network policy gives
you none of those.

**3. Policy language.** Deliberately small; capped at eight kinds; the
reasons are in [why-not-just-opa.md](../policies/why-not-just-opa.md).
What is left when you use OPA: identity binding, delegation intersection,
grant binding, interception, evidence, replay, impact, regression. OPA
answers a question; it does not run the loop. The `Policy` boundary is
where an OPA/Cedar adapter goes; not built, listed under P2 with the reason.

**4. Trust anchor.** Accurate description of v0.3.0, and it is written in
the threat model as O1/O4/O6/O10 with severities, not discovered by this
review. The kernel is small enough to check: an exhaustive state-machine
enumeration (every operation sequence to length 5, both stores) and a
Hypothesis stateful test interleaving tampering, revocation, expiry and
replay ([grant-lifecycle.md](../formal/grant-lifecycle.md)). One real bug
came out of that (F18) and was fixed before release. HA and asymmetric
grants are roadmap items with a design, not promises.

**5. Bearer tokens.** Yes. Expiry, revocation re-checked under the lock,
audience-bound grants, and an `IdentityProvider` protocol with a second
implementation tested so mTLS/SPIFFE/DPoP can replace it without touching
the kernel ([identity-providers.md](../security/identity-providers.md)).
The limitation is on the README's security list.

**6. What regression tests test.** They test *the decision function over a
pinned authority graph and policy set*. That is exactly the thing that
changes when someone edits a policy, widens a grant, or refactors the
engine — and exactly what no other tool pins. They do not test the agent
or the prompt; the docs say so in the "Limits" section. Determinism is not
free: it is a property test (`test_decision_is_deterministic_and_bounded_by_authority`).
The value is the *pin*, not the determinism.

**7. Mutation.** The docstring cites the prior art and says this is
request-side, not policy-side. The list is small on purpose; every mutant
is decided by the real kernel; mutations that leave the recorded authority
are marked *must deny* and an ALLOW there is a kernel bug — which is a
useful oracle no for-loop provides. It found nothing in this pass, which is
the expected result, and it exits 1 if it ever does.

**8. Benchmarks.** Both numbers are published side by side with method,
hardware and n, and the cold column exists *because* it is unflattering.
The first call includes process start of the upstream and the proxy. The
benchmark also found the 50 ms wrap path was an artifact of a per-request
event loop and fixed it to 14 ms; that is what benchmarks are for. No
"faster than" claim is made anywhere.

**9. Zero users.** True, stated on the README's first screen, in the
compatibility matrix, and in the pre-mortem. The matrix marks VERIFIED only
what was run; that is the point of it. Linux is the first item after
publication because the CI workflow cannot run before there is a remote.

**10. Annotations.** The generator uses them to *propose* capability names
in a file a human reviews; destructive tools are never delegated by the
generator; the first-user test shows the safe default biting (the first
write was denied); the residual risk of a lying server is O21 in the
security review. Verifying side effects is not expressible in MCP today;
it is under RESEARCH in the roadmap.

## What the review gets right and nothing above answers

- There are no users. Everything else is a claim about a codebase, not
  about value delivered.
- The operator key on a developer's disk is the whole trust model of the
  local-first deployment. That is fine for development and CI; it is not a
  production security architecture, and `atp serve` with separated keys is
  where that work goes.
- The dashboard exists and is not part of the loop. It is frozen, not
  removed.
