# Agent Security Regression Pack

*A concrete, fixed-scope engagement. No customers, revenue, certifications or
production deployments are claimed; the method is the one used to build and
test the open-source project, and the deliverables are the artifacts that
project produces.*

## The deliverable

For one agent workflow that touches real tools, you receive:

1. **A tool workflow map** — every consequential tool the agent can call,
   with its arguments, the resource it acts on, who delegates the authority
   to call it, and the current limit (if any). One page per workflow.
2. **A reproducible security regression suite** — YAML cases in the format
   `atp test` runs, one per dangerous action we could make the agent attempt
   in staging: injection via documents or tool output, over-limit actions,
   redirected destinations, delegation escalation, one agent using another's
   authority. Each case pins the decision you want kept.
3. **Documented authorization failures** — every case that was *allowed* when
   it should not have been, with the recorded trace (envelope, resolved
   authority, policy results, side effect), severity, and what let it through.
4. **Recommended policy changes** — concrete, in your terms: which limit or
   scope to add, where the delegation graph is too wide, which tool needs an
   argument-level check. Where it helps, the change is shown as a policy-set
   diff you can replay against the recorded cases.
5. **Before/after evidence** — the same recorded actions replayed under the
   hardened policy: which decisions flipped, which did not, with traces.
6. **CI integration where feasible** — the suite wired into your pipeline
   (GitHub Actions or equivalent) so it runs on every change, with JUnit
   output; no secrets, no side effects.
7. **Deployment limitations, stated** — where the control cannot bite in your
   architecture (tools reachable without the gateway, agents holding
   long-lived credentials, transports not supported), and what closing each
   gap would take.

## What is required from you

- One workflow to start with, and the action you would least like it to take.
- Read access to the agent's prompts, tool definitions and orchestration
  code, or a two-hour walkthrough with an engineer.
- A staging environment (or sandbox) where the same tools point at fake or
  reversible backends. Nothing is run against production.
- ~2 hours/week of an engineer's time for three weeks, and a window later to
  rerun the suite after fixes.

## Shape and price hypothesis

Three weeks part-time plus a rerun. Fixed scope: up to 3 agents, 10 tools,
1 staging environment.

| | |
|---|---|
| Introductory assessment (90 min, live, one-page finding) | free for the first five teams, in exchange for candid feedback |
| Regression Pack (everything above) | **USD 6,000–9,000 fixed**, a hypothesis to be validated with the first three conversations |

## Exclusions

Model red-teaming for harmful content; compliance certification; network or
cloud penetration testing outside the agent's tool surface; building the
fixes (separate engagement); any guarantee beyond "here is exactly what was
tested and what happened".

## Why this and not a checklist

The open-source project shows the method working end to end on a real MCP
server: a tool call intercepted over the wire, decided against delegated
authority, blocked before execution, recorded, replayed under a changed
policy, and pinned as a CI test. The pack applies that loop to your workflow.
The general audit offer (`agent-production-readiness-audit.md`) is the wider,
consulting-shaped version; this pack is the narrow, artifact-shaped one.
