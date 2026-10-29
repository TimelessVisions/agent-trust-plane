# Agent Trust Plane × Photon — Founder Demo Runbook

This demonstration proves a narrow, important claim: an agent can use tools, while an independent control plane enforces delegated limits, records evidence, and makes enforced denials visible to a human.

## What is real

- A real MCP notes server is wrapped by ATP.
- `write_note` is allowed, forwarded, and executed.
- `delete_note` requires `notes:destroy`, which the agent was not delegated.
- ATP returns an enforced `DENY`; the delete never reaches the notes server and the note still exists.
- The denial has a hash-chained trace, a deterministic reason code, and a regression case.
- On October 28, 2026, the user confirmed both a manual and an automatic ATP-denial alert arrived on a real iPhone through Photon shared iMessage.

The scenario is deterministic and local. It uses no LLM, no real payment, no fabricated customer or usage metric, and no inbound text-message approval.

## Event setup

Use the `feat/photon-denial-alerts` checkout. Do not merge either draft PR for the event.

```zsh
cd ~/Projects/agent-trust-plane
git switch feat/photon-denial-alerts
git pull --ff-only
uv sync --frozen --python 3.12
```

Terminal 1 — optional live iMessage leg. Load the existing Spectrum project credentials locally, then enter the destination without putting it in the repository or slides:

```zsh
cd ~/Projects/agent-trust-plane
read -s "ATP_DEMO_PHONE?Demo iPhone in E.164 format: "
echo
export ATP_DEMO_PHONE
uv run --frozen --python 3.12 atp photon watch \
  --transport spectrum \
  --to "$ATP_DEMO_PHONE" \
  --home photon-demo/.atp
```

Leave Terminal 1 running. It baselines old traces, sends only fixed alerts for new integrity-valid enforced denials, and never interprets replies as commands.

Terminal 2 — visual demo:

```zsh
cd ~/Projects/agent-trust-plane
uv run --frozen --python 3.12 python scripts/founder_demo_server.py \
  --out photon-demo
```

Open `http://127.0.0.1:8765`, put the browser in full screen, and click **Run the trust boundary**. The screen executes the real MCP demo and then reads the resulting ATP store; it does not use fixtures or browser-only simulated results.

## 30-second pitch

“AI agents can already act. The missing layer is enforceable trust. Here the agent can write a note, so ATP lets the call through. Then the same agent tries to delete it. Delete authority was never delegated, so ATP blocks the call before it reaches the tool. We get a hash-chained trace, a precise reason, and an automatic security alert on the founder’s iPhone. The message is visibility—not approval. The model proposes; ATP decides what can actually execute.”

## 2-minute script

“Most agent safety today lives in prompts: tell the model what not to do and hope it complies. Agent Trust Plane starts from a different premise. Models propose actions; independent infrastructure decides whether those actions may execute.

This is a real MCP notes server behind ATP. The human delegated read and write, but never delete. First, the agent writes ‘buy milk.’ ATP resolves identity and the delegation chain, sees `notes:write`, and allows the request. The upstream server executes it.

Now the wow moment: the same agent attempts `delete_note`. The proxy requires `notes:destroy`. The agent does not have it. ATP returns an enforced DENY before the request reaches the notes server. The note still exists.

That decision is not just a red badge. ATP records who acted, for whom, which capability was requested, the policy version, the reason code, and a hash-chained evidence trace. We immediately pin the denial as a regression test, so a later policy change cannot silently widen authority.

Separately, an outbound watcher sees the new integrity-valid enforced denial and asks Photon to deliver a fixed security alert over iMessage. We have already confirmed both manual and automatic alerts on a real iPhone. A reply cannot approve the action or modify policy.

This is demo-ready, not production-ready. The watcher is local and polling, delivery still needs device confirmation, and open Python and npm dependency audits must be resolved. But the core product truth is working: agents can act, ATP sets enforceable limits, evidence explains every decision, and humans get immediate visibility.”

## 5-minute script

### 0:00–0:45 — The problem

“We are giving agents tools that write data, move workflows, and eventually touch money. Prompt instructions are useful, but they are not an authorization boundary. A capable or manipulated model can still propose the wrong action. We need a layer outside the model that answers a simpler question: is this exact action inside the authority this agent was actually given?”

Point to the headline: “The model proposes. ATP decides.”

### 0:45–1:30 — The boundary

Point to the architecture. “The agent is untrusted. Every consequential MCP tool call crosses the ATP proxy and gateway. ATP resolves identity, intersects the delegation chain, evaluates versioned policy, and produces ALLOW, DENY, or a held decision. In this demo we use enforced mode. Shadow mode would only observe and would not prove prevention.”

“The evidence store and Photon watcher are downstream observers. Neither can change the decision. There is deliberately no approval by text message.”

### 1:30–2:45 — Run the wow moment

Click **Run the trust boundary**.

“This is a deterministic local scenario against a real MCP notes server—no LLM theatre and no payment. The agent has read and write authority.”

When step 01 turns green: “The write is inside delegated authority, so ATP forwards it and the note is created.”

When step 02 turns red: “The agent now asks to delete the same note. Delete requires `notes:destroy`; that capability is absent. ATP stops the call before the upstream server. The note still exists.”

### 2:45–3:45 — Evidence and visibility

“The denial has a stable trace ID, `CAPABILITY_NOT_GRANTED`, an enforced-mode marker, and a valid hash chain. The demo converts it into a regression test and runs that test immediately. This is how a security decision becomes durable engineering evidence rather than a screenshot.”

If the Photon watcher reports request accepted: “Photon accepted the outbound request. That is not the same as device delivery, so I will confirm the iPhone before claiming the live alert arrived.” Show the phone only if the new alert is visibly present.

### 3:45–4:30 — Why it matters

“The pattern generalizes: support agents may refund but not change payout destinations; coding agents may edit a workspace but not production secrets; procurement agents may draft a purchase but not exceed a delegated limit. ATP makes authority explicit and enforcement independent from model behavior.”

### 4:30–5:00 — Honest close

“This proof of concept is demo-ready, not production-ready. The local watcher must become a hardened service; transport delivery needs operational monitoring; the boundary must be impossible to bypass in deployment; and open dependency findings must be cleared. Telegram exists only in a separate unverified draft. What is already real is the critical loop: allow the legitimate action, block the unauthorized one, preserve evidence, and tell a human immediately.”

## Investor / founder Q&A

**Is this another prompt guardrail?**
No. The model can propose any action. ATP independently evaluates the exact tool, arguments, resource, identity, and delegated authority before execution.

**What proves the delete was actually blocked?**
The proxy did not forward the call, the trace records an enforced DENY, no execution-completed event exists, and the note remains on disk. The decision is then reproduced by a regression test.

**Can someone reply “approve” to the iMessage?**
No. The integration is outbound-only. Replies are not parsed and cannot change grants, policy, or a decision.

**What is the difference between enforce and shadow?**
Enforce blocks the action. Shadow records what ATP would have decided but permits the existing execution path. This demo uses enforce; a shadow result must never be described as blocked.

**Does the demo move money?**
No. It writes and protects a local note. Repository finance scenarios are synthetic; this event flow performs no payment.

**Is Photon delivery guaranteed?**
No. The local journal distinguishes request accepted from uncertain, and it never retries an ambiguous attempt automatically. Actual iMessage delivery is confirmed on the device.

**Does Telegram work?**
The implementation is in separate draft PR #3, but real delivery is unverified. Label it beta and do not demo or claim it until a device acceptance test passes.

**Can an agent bypass ATP?**
If it can reach or launch the upstream tool directly, yes. Production deployment must make ATP the enforced network/process boundary and deny alternate paths. The demo states this limitation explicitly.

**Is this production-ready?**
No. It is a credible working proof of concept. Production work includes service hardening, TLS/KMS and separated credentials, scalable event delivery, monitoring, recovery procedures, bypass-resistant topology, and dependency remediation.

**What are the known security blockers?**
Issue #2 tracks locked Python advisories. Issue #4 tracks the Spectrum SDK’s transitive npm findings and calls for a reproducible lockfile, compatible upgrades, and explicit risk review. Neither should be suppressed merely to make CI green.

**How big is adoption?**
No user, revenue, or usage metric is claimed in this demo. The evidence is technical: reproducible enforcement, tests, traces, CI, and two real-device iMessage confirmations.

## Fallback ladder

1. **Wi-Fi fails:** run the core demo normally; it is local. Say: “The enforcement and evidence path is live; the event transport is unavailable. The same automatic iMessage path was previously confirmed on a real iPhone.”
2. **Photon is unavailable:** show Terminal 1 honestly. “Accepted” means the provider accepted the request; it is not device-delivery proof. If uncertain, say so and do not retry automatically.
3. **Visual UI fails:** run `uv run --frozen --python 3.12 atp demo wrap --out photon-demo` in a large terminal. Narrate the ALLOW, enforced DENY, unchanged note, policy explanation, and passing regression.
4. **Local run fails:** use the prepared screenshot and recorded terminal transcript, explicitly labeled “recorded fallback,” then return to the architecture and Q&A. Never present recorded output as a current live run.

## Readiness boundary

| Demo-ready now | Required before production |
|---|---|
| Enforced allow/deny on a real MCP server | Bypass-resistant deployment topology |
| Hash-chained local evidence and regression pinning | Hardened service, TLS, KMS, credential separation |
| Manual and automatic iMessage receipt confirmed on one real device | Delivery monitoring, reconciliation, scale and recovery |
| At-most-one-attempt local alert journal | Resolve Python issue #2 and npm issue #4 |
| Outbound-only alerts; no text approvals | Formal operational/security review |
| Telegram clearly labeled unverified beta | Real Telegram device acceptance before any claim |
