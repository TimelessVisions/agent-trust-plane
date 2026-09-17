# AI Agent Production Readiness Audit — pilot offer

*Working draft. No customers, certifications, or production deployments are
claimed. The method is the one used to build and red-team Agent Trust Plane;
the reference implementation is open source and inspectable.*

## Who it is for

Startups and small teams that have an LLM agent in staging or early
production which can reach at least one of: payments or refunds, customer or
employee data, internal systems (CRM, ERP, ticketing, code, infrastructure),
third-party APIs, or other agents — and where a wrong action costs real
money, real data, or real trust.

Typical trigger: "The agent works. Someone asked what happens if it's told to
do something else."

## What is assessed

Each line is an attempt against your system, not a questionnaire.

| Area | The concrete question |
|---|---|
| Prompt injection | Can content the agent reads (documents, email, web, tool output) change what it does? We plant instructions and watch the tool calls. |
| Tool permissions | What can each agent call, with which arguments, on which resources — and is that written down where the agent can't edit it? |
| Delegated authority | When agents call agents, can a child exceed its parent? Can one agent act on another's authority or identity? |
| Sensitive-data boundaries | What can flow into a prompt, out to a tool, or into a log? |
| Destructive actions | Which actions are irreversible, and what gates them beyond a prompt? |
| Failure recovery | What happens on a partial tool failure, timeout, or retry — does anything execute twice? |
| Unbounded loops and cost | What stops an agent calling itself, a tool, or another agent indefinitely? What is the budget, and who enforces it? |
| Third-party tool responses | Are tool results treated as untrusted input? |
| Auditability | After an incident, can you reconstruct what the agent saw, proposed, was allowed, and did — from records the agent couldn't alter? |
| Reproducibility | Can you rerun the failing case deterministically and prove a fix changed the outcome? |

## What you receive

1. **Risk map** — one page per area: what was tried, what happened,
   severity, and the mechanism (or absence) responsible.
2. **Reproducible eval suite** — runnable scenarios against your stack with
   expected results and PASS/FAIL output. Yours to keep and put in CI.
3. **Evidence traces** — the recorded runs behind every finding.
4. **Failure report** — ranked findings written for the engineer who fixes
   them and the leader who decides.
5. **Remediation plan** — concrete: which check goes where, what to gate,
   what to log, what to bound. Where a bounded-authority / signed-grant /
   replayable-trace pattern applies, the recommendation shows it in your
   architecture, with the open-source reference as a worked example.
6. **Before/after rerun** — the same suite after your fixes, showing which
   findings closed.

## Engagement shape

- **Week 1** — scope and inventory: agents, tools, data, delegation paths,
  the three actions you most fear. Access to staging or a faithful sandbox.
- **Week 2** — adversarial evaluation. Daily written findings.
- **Week 3** — report, remediation plan, suite handover, walkthrough.
- **Rerun** — scheduled when fixes land, typically 2–6 weeks later.

Three weeks of part-time engagement plus the rerun.

## Pilot pricing hypothesis

A fixed-scope pilot: up to **3 agents, 10 tools, 1 staging environment**.

| Tier | Scope | Hypothesis |
|---|---|---|
| Introductory assessment | 90-minute session: I run two injection and one authority scenario against one agent live, and give you a written one-page finding | Free for the first five teams, in exchange for candid feedback and permission to describe the anonymised findings pattern |
| Pilot audit | Full three-week engagement above, single environment, rerun included | **USD 6,000–9,000 fixed** (hypothesis to validate with the first three conversations; anchored on ~30–40 hours of senior engineering time plus the reusable suite) |
| Follow-on | Additional environments or agents, control-plane implementation support | Scoped separately |

These are starting hypotheses, not a validated price list. The first three
pilots will set the real number.

## What I need from you

- A one-paragraph description of the workflow and the action you'd least
  like the agent to take by mistake.
- Read access to the agent's prompts, tool definitions, and orchestration
  code (or a walkthrough with an engineer).
- A staging environment or sandbox with the same tools wired to fake or
  reversible backends, and one engineer available for ~2 hours/week.
- Whatever logs or traces you already produce.

## What is tested where

**Safe in staging:** injection via documents and tool output; permission and
delegation boundaries; identity confusion between agents; grant/approval
replay; loop and budget behaviour; log and trace reconstruction. All with
fake or reversible backends.

**Never in production:** nothing is run against production systems,
production data, or live payment rails. If a finding can only be confirmed
in production, it is reported as unconfirmed with the staging evidence.

## Exclusions

- Model red-teaming for harmful content, bias, or jailbreak research.
- Compliance certification (SOC 2, ISO, PCI). The output is evidence you can
  bring to those processes, not a badge.
- Penetration testing of your network, cloud accounts, or web app outside
  the agent's tool surface.
- Building the fixes (available as a separate engagement).
- Any guarantee. The report states exactly what was tested and what was not.

## Basis for the method

The method is the one applied to Agent Trust Plane, an open-source control
plane with an eight-scenario adversarial suite and 300+ tests, including a
documented self-review with fixed and open findings
(`docs/security-review.md`). That project is an MVP built by one engineer;
it is offered as evidence of method and rigor, not of production experience
with payment systems.
