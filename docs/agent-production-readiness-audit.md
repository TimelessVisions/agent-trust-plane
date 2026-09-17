# AI Agent Production Readiness Audit

*See [commercial-offer.md](commercial-offer.md) for the concise offer, pilot
pricing hypothesis, exclusions, and what is tested where, and
[prospect-message.md](prospect-message.md) for the outreach note.*

A fixed-scope engagement for teams putting LLM agents in front of real
systems. The output is evidence, not opinion: a reproducible eval suite run
against your actual agent stack, the traces it produced, and a before/after
rerun once fixes are in.

## Who it is for

Startups and companies deploying LLM or agent workflows that touch:

- real tools and third-party APIs;
- customer or employee data;
- internal systems (CRMs, ERPs, ticketing, code, infrastructure);
- payments, refunds, credits, or anything that moves money;
- production workflows where an agent's action has a cost to undo.

Typical trigger: "We have an agent in staging that can do X, and someone
asked what happens if it's told to do Y."

## What the audit covers

Each area is assessed against your system, with a concrete attempt where
possible, not a questionnaire.

| Area | The question | Evidence produced |
|---|---|---|
| **Prompt injection** | Can content the agent reads (documents, email, web pages, tool output) change what it does? Direct and indirect. | Injection attempts with recorded outcomes; which ones reached a tool call |
| **Tool permissions** | Which tools can each agent call, with which arguments, on which resources? Is the answer written down anywhere the agent cannot edit? | Tool/permission matrix; over-broad tools flagged |
| **Delegated authority** | When agents call agents, does authority narrow or leak? Can a child exceed its parent? Can a helper act on a grant that isn't its own? | Delegation graph; escalation attempts and results |
| **Sensitive-data boundaries** | What data can flow into a prompt, out to a tool, or into a log? Is PII/secret exposure detectable after the fact? | Data-flow map; exposure tests |
| **Destructive actions** | Which actions are irreversible (delete, send, pay, deploy)? Are they gated, dual-controlled, or just prompted? | List of irreversible actions and their current gate |
| **Failure recovery** | What happens on a partial tool failure, a timeout, a retry? Does anything execute twice? | Fault-injection results; idempotency findings |
| **Unbounded loops** | Can the agent call itself, a tool, or another agent indefinitely? What stops it? | Loop attempts; observed termination (or not) |
| **Cost explosions** | Is there a per-task, per-agent, or per-window budget in tokens, calls, and money? | Budget review; a runaway scenario with measured cost |
| **Third-party tool responses** | Are tool results treated as untrusted input? Can a tool response inject? | Tool-output injection attempts |
| **Auditability** | After an incident, can you reconstruct what the agent saw, proposed, was allowed, and did — from records the agent could not alter? | Sample incident reconstruction from your logs |
| **Reproducibility** | Can you rerun a failing case deterministically and prove a fix changed the outcome? | Replay demonstration, or the gap documented |

## Deliverables

1. **Risk map** — one page per area: what was tested, what happened,
   severity, and the specific mechanism (or absence) responsible.
2. **Reproducible eval suite** — runnable scenarios against your stack,
   each with an expected result and a PASS/FAIL report. Yours to keep and
   put in CI.
3. **Evidence traces** — the recorded runs behind every finding, so
   engineering can see exactly what the agent proposed and what executed.
4. **Failure report** — the findings that matter, ranked, written for the
   engineer who will fix them and the leader who has to decide.
5. **Remediation recommendations** — concrete: which check goes where, what
   to gate, what to log, what to bound. Where a control plane pattern
   applies (bounded authority, signed execution grants, replayable traces),
   the recommendation shows what it would look like in your architecture.
6. **Before/after rerun** — after your team applies fixes, the same suite
   is rerun and the report shows which findings closed and which remain.

## How it runs

- **Week 1 — scope and inventory.** Agents, tools, data, delegation paths,
  the three actions you most fear. Access to a staging environment or a
  faithful sandbox.
- **Week 2 — adversarial evaluation.** Scenarios built and run. Daily
  written findings so nothing waits for the report.
- **Week 3 — report and remediation plan.** Walkthrough with engineering
  and leadership. Eval suite handed over.
- **Follow-up — rerun.** Scheduled when fixes land; typically two to six
  weeks later.

Fixed price for a defined scope (a number of agents, tools, and
integrations agreed up front). Larger estates are scoped as phases.

## What you get that you can't get from a checklist

The reference implementation behind this audit is open source: a working
control plane with authenticated agent identity, delegated authority, a
policy engine, execution grants bound to authorized actions, hash-chained
traces, replay, and an eval harness that runs the same attacks against it —
plus a written self-review with open findings. The audit applies the same
adversarial method to your system, and the recommendations point at
mechanisms that exist and are tested, not at slideware. It is an MVP by one
engineer; it demonstrates method, not production track record.

## What this is not

- Not a model red-team. The question is not "can the model be made to say
  something bad" but "can anything the model says cause your systems to do
  something it was not allowed to do."
- Not a compliance certification. It produces evidence you can use in a
  compliance process; it does not issue a badge.
- Not a guarantee. The report states what was tested and what was not.

## Starting point

Send a one-paragraph description of the agent workflow, the tools it can
reach, and the action you would least like it to take by mistake. That is
enough to scope a first conversation.
