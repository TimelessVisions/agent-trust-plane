# Photon iMessage denial alerts (experimental)

**Scope:** an explicit CLI action sends a **read-only**, minimal notification
for an **integrity-verified, enforced DENY** decision in ATP's local trace
store. This is not a webhook service, an approval flow, an automatic alert
stream, or proof of message delivery. It does not change how ATP authorizes,
blocks, executes, or audits tool calls.

Photon 2.0 uses a project-scoped API with Users, Spaces, and Messages:
https://photon.codes/blog/introducing-photon-2.0

## Prerequisites (operator actions)

1. Create a Photon 2.0 project in its dashboard, provision an iMessage-capable
   agent line, and obtain a **project API key** with the required permission.
   Confirm that the recipient is allowed in your Photon plan.
2. Obtain the project ID and the agent's **User ID on the iMessage platform**.
   The agent User ID is **not** a phone number.
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

### Security promises / limits

- **No auto-send**: the operator explicitly selects a trace and recipient.
- **No outgoing arbitrary text**: the formatter is limited to ATP's recorded
  trace ID, fixed reason code, and enforced DENY status.
- **No prompt text, payment amounts, destination identifiers, credentials,
  arguments, policy explanation, or user content** in the message.
- **No alert from altered evidence**: invalid trace integrity is rejected.
- **No shadow-mode confusion**: WOULD_DENY cannot be sent as a real block.
- **No alternate authorization path**: iMessage replies are ignored. No
  approval, execution, policy modification, or grant issuance is added.
- **No automatic retries** after an ambiguous transport error. Photon may have
  accepted an operation even when its response was lost.
- A stable idempotency key accompanies each request, but the service's
  retention window is external; repeated manual sends are **not guaranteed**
  exactly-once.
- Do not use the local operator's complete trace data in Photon. Even the
  minimal trace ID and reason leave your machine, so use a recipient you
  control and a test trace with no sensitive metadata in its ID.

### Future work (not implemented here)

- A durable, opt-in, privacy-reviewed event/outbox worker for automated alerts.
- A signed inbound webhook receiver with authenticated user mapping, replay
  protection and message deduplication.
- An operator-facing read-only trace lookup via authenticated messaging.
- Separately designed **human approvals** tied to the exact action hash, human
  approver identity, TTL and existing delegation/policy constraints.

Do **not** advertise any of these as built or use SMS text as an
authorization override. Read the main ATP threat model before a production
pilot: ../security/threat-model.md.
