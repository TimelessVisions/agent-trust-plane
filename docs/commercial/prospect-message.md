# Prospect message — introductory assessment

*Short, specific, no claims that aren't true. Adjust the bracketed parts.*

---

**Subject:** what your agent does when the invoice tells it to

Hi [name],

I noticed [team/product] has an agent that can [pay vendors / issue refunds /
update CRM records / call internal APIs]. I've been working on exactly the
failure mode that worries me about those: the model reads an untrusted
document, the document contains instructions, and the model follows them —
and nothing between the model and the tool asks whether it was allowed to.

I built an open-source control plane for this (bounded delegated authority,
signed single-use execution grants, replayable hash-chained traces) and an
adversarial eval suite that runs real attacks against it — injection,
delegation escalation, agent impersonation, grant replay. It's an MVP, not a
product, and its limitations are written down next to its results.

I'd like to run the same three scenarios against one of your agents in a
staging environment: an injected instruction in a document, an over-limit
action, and an agent using another agent's authority. Ninety minutes, live,
with you watching. You get a one-page written finding either way.

I'm doing this for the first five teams at no charge, in exchange for candid
feedback on whether the finding was useful.

If that's interesting, reply with one line: the action you'd least like the
agent to take by mistake. That's enough for me to scope it.

[name]
[link to repo]

---

*Follow-up if no reply after a week (one line):* "Still happy to run this if
timing was the issue — or if the agent isn't near real tools yet, tell me and
I'll stop."
