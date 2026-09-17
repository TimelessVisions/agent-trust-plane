# ADR-0003: Category definition — action control and security regression infrastructure for AI tool use

Status: Accepted
Date: 2026-09-17
Supersedes the positioning paragraph of ADR-0002 (its technical decisions stand).

## Inputs

`docs/architecture/first-principles.md`, `docs/architecture/premortem.md`,
`docs/research/competitive-code-review.md`, `docs/research/user-pain.md`.

## Five candidate positions

Each was scored internally on clarity, urgency, differentiation,
usefulness, implementation truth (does the code do it today?), future
resilience (survives MCP turnover?), open-source appeal and commercial
relevance. Scores are not published; the reasoning is.

1. **"An MCP security proxy."** Clear and urgent (tool poisoning is in
   the news), but undifferentiated (four funded gateways), weak on
   implementation truth (stdio, one upstream) and fails the
   future-resilience test (dies with MCP). Rejected.

2. **"Authorization server for AI agents."** Differentiated by delegated
   authority and execution grants, true to the code, resilient. But the
   phrase lands as "yet another policy engine" and undersells the
   evidence/regression half that nobody else has. Rejected as the
   headline; kept as the description of the kernel.

3. **"Security regression infrastructure for AI tool use."** Highly
   differentiated (no competitor), true to the code after this pass,
   resilient (suites and bundles are protocol-neutral), strong developer
   appeal (CI is where developers live). Weakness: on its own it sounds
   like an eval tool, and evals do not *stop* anything; urgency is lower
   than the incident-driven proxy framing.

4. **"An agent action firewall."** Urgent and clear; suggests enforcement.
   But "firewall" implies content inspection and network placement, which
   we do not do, and it hides replay/regression entirely.

5. **"Agent action control + security regression infrastructure."**
   Combines 2 and 3: the kernel authorizes and binds; the loop records,
   replays and pins. Clear once stated as a loop; most differentiated;
   fully true after this pass; resilient; appeals to both developers
   (regression, CI) and security (control, evidence). Weakness: two
   nouns; mitigated by leading with the loop, not the nouns.

## Decision

Position 5. The public one-line positioning is:

> **Put a real authorization boundary between your AI agent and its
> tools, and turn every dangerous action into a regression test so it
> cannot silently come back.**

The category name used in docs is **action control and security
regression infrastructure for AI tool use**.

The primary user is the developer who owns an agent that can take
consequential actions (files, payments, tickets, deployments) and who
needs, in this order: to see what it tries to do, to bound it without
rewriting it, to prove a fix, and to keep it fixed in CI. The secondary
user is the security engineer who reviews that developer's evidence.

The primary workflow (the loop):

```
wrap   →  observe/decide  →  execute or block  →  record  →  explain
       →  harden policy   →  replay / impact  →  regression add  →  CI
```

## Consequences

- The CLI is the product surface; the dashboard is frozen at
  before/after evidence.
- We ship one integration well (MCP proxy, stdio served, stdio or
  Streamable HTTP upstream) and document decision-only hooks for
  frameworks instead of building weak adapters.
- Policy authoring gets a small declarative format so the loop works
  without editing Python; the format is capped and the policy boundary
  is designed to host OPA/Cedar later (`docs/why-not-just-opa.md`).
- Shadow mode exists so "wrap" can precede "enforce", and is declared by
  the gateway, never requested by the caller.
- No SARIF: authorization regressions are test results, not static
  analysis findings; JUnit + JSON are the CI formats.
- Everything the loop produces (suites, bundles, explanations, impact
  reports) is a file that survives a change of protocol or model.
