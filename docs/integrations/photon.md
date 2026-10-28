# Photon iMessage denial alerts (experimental)

**Scope:** an explicit CLI action sends a **read-only**, minimal notification
for an **integrity-verified, enforced DENY** decision in ATP's local trace
store. An **opt-in local watcher** can send new denials while running, with a
durable at-most-one-attempt journal. It is not a hosted webhook, an approval
flow, or proof of message delivery. It does not change how ATP authorizes,
blocks, executes, or audits tool calls.

Photon 2.0 uses a project-scoped API with Users, Spaces, and Messages:
https://photon.codes/blog/introducing-photon-2.0

## Prerequisites (operator actions)

1. Create a Photon 2.0 project in its dashboard, provision an iMessage-capable
   agent line, and obtain a **project REST API key** (`pho_sk_...`) with the required permission.
   Confirm that the recipient is allowed in your Photon plan.
2. Obtain the project ID and the agent's **User ID on the iMessage platform**.
   The agent User ID is **not** a phone number.
   The Photon CLI's Spectrum `projectSecret` (`spk_live_...`) is a **different
   credential** and should not be substituted for the REST API key.
3. Keep the credentials **outside Git**, server-side only. Do not put them in
   a web or React Native environment variable with a PUBLIC prefix.
4. Run the commands below on a machine that contains the local ATP traces.
   The source repo needs Python >=3.12 and uv.

PowerShell, from the root of the ATP repository:

```powershell
uv run atp demo wrap --out photon-demo
uv run atp trace list --home photon-demo/.atp
```

Choose an actual enforced DENY trace from the list (not ALLOW or WOULD_DENY).
Substitute its ID. The dry run **does not need** any Photon credentials.

```powershell
uv run atp photon notify TRACE_ID --to +12125550123 --home photon-demo/.atp --dry-run
```

Once the privacy-limited preview is correct, set the following process
environment variables in your own terminal or a secrets manager. Avoid
copying their real values into chat, screenshots, or version control:

```powershell
$env:PHOTON_PROJECT_ID = "YOUR_PHOTON_PROJECT_ID"
$env:PHOTON_API_KEY = "YOUR_SERVER_SIDE_PROJECT_KEY"
$env:PHOTON_AGENT_USER_ID = "YOUR_IMESSAGE_AGENT_USER_ID"
uv run atp photon notify TRACE_ID --to +12125550123 --home photon-demo/.atp
```

The command creates or resolves the recipient User and conversation Space and
then requests a plain text Message through the Photon 2.0 API. A success
message means **Photon accepted the API request**, not that an iPhone
received it. Verify delivery in your Photon dashboard and on the device.

### Optional: automatically notify on new denied actions

Use a separate PowerShell terminal so the watcher stays running. It sends
only new, integrity-verified enforced DENY decisions, not historical alerts:

```powershell
uv run atp photon watch --to +12125550123 --home photon-demo/.atp
```

With that command running, create a *new* blocked action in another terminal
using a test/demo agent. For a standalone local demonstration using this repo:

```powershell
uv run atp demo wrap --out photon-demo
uv run atp trace list --home photon-demo/.atp
```

The watcher records its own state in \`photon-demo/.atp/photon-alerts.db\` and
ignores all traces that existed when it first started. Do not delete the
journal to force another send: that would reset its history boundary.
\`--once\` makes a single scan for tests; otherwise use Ctrl+C to stop.

The watcher claims a trace **before** the Photon request. An ambiguous
error or crash may leave an alert marked as \`unknown\`; it is never
automatically resent. ATP authorization is not delayed or affected if
Photon is unavailable. This polling prototype looks at only the most recent
500 traces per interval and is **not** designed for high-volume production.
A transactional outbox/event sink is required for reliable scale.

### Create the Photon project on Windows

From PowerShell, using Photon's published CLI:

```powershell
npm.cmd install --global @photon-ai/cli
photon whoami
# If not signed in:
photon login
photon projects create --name "Agent Trust Plane" --platforms imessage
# Copy the returned project ID into your local process environment:
$env:PHOTON_PROJECT_ID = "YOUR_PROJECT_ID"
photon projects show
photon spectrum lines list
```

A newly created project may use a shared line. Confirm the line is usable
in the dashboard. To run *this REST integration*, also obtain the
**Project REST API key** (not the CLI's Spectrum project secret) and the
agent's platform User ID from the dashboard. Never post them in chat,
issues or pull requests. Do not create paid/dedicated lines unintentionally.

### Security promises / limits

- **Opt-in send only**: `notify` requires an explicit trace; `watch` must be explicitly started with a fixed recipient and never replays existing history.
- **No outgoing arbitrary text**: the formatter is limited to ATP's recorded
  trace ID, fixed reason code, and enforced DENY status.
- **No prompt text, payment amounts, destination identifiers, credentials,
  arguments, policy explanation, or user content** in the message.
- **No alert from altered evidence**: invalid trace integrity is rejected.
- **No shadow-mode confusion**: WOULD_DENY cannot be sent as a real block.
- **No alternate authorization path**: iMessage replies are ignored. No
  approval, execution, policy modification, or grant issuance is added.
- **No automatic retries** after an ambiguous transport error. Photon may have
  accepted an operation even when its response was lost. The watcher records
  the attempt before sending and does not retry uncertain outcomes.
- A stable idempotency key accompanies each request, but the service's
  retention window is external; repeated manual sends are **not guaranteed**
  exactly-once.
- Do not use the local operator's complete trace data in Photon. Even the
  minimal trace ID and reason leave your machine, so use a recipient you
  control and a test trace with no sensitive metadata in its ID.

### Future work (not implemented here)

- A durable production-grade transactional outbox/event sink for alert delivery.
- A signed inbound webhook receiver with authenticated user mapping, replay
  protection and message deduplication.
- An operator-facing read-only trace lookup via authenticated messaging.
- Separately designed **human approvals** tied to the exact action hash, human
  approver identity, TTL and existing delegation/policy constraints.

Do **not** advertise any of these as built or use SMS text as an
authorization override. Read the main ATP threat model before a production
pilot: ../security/threat-model.md.
