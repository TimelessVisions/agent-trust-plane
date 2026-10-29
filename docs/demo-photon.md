# Photon presenter runbook

Use this on stage. The rehearsal needs no phone, no Photon or Spectrum
credentials, and no network. The live path is the same alert, sent only when
you opt in with Spectrum credentials on a machine that has the owner's iPhone
registered.

The alert is read-only. It contains the enforced DENY status, the trace ID,
and the reason code. It does not contain tool arguments, prompt text, or
amounts. Replies cannot approve an action, change a grant, or execute
anything. ATP authorization does not wait on Photon.

## What is verified

| Path | Status |
|---|---|
| `uv run atp demo photon` (this runbook's rehearsal) | Runs in CI. No network. |
| Manual send through `integrations/photon-spectrum/send.mjs` | One message confirmed on a real iPhone, 2026-10-28. |
| Automatic delivery via `atp photon watch` | Not verified on a device. Needs the owner's Mac and phone. |

Keep the pull request a draft until that watcher delivery has been seen on
the phone. A green CI run does not prove carrier delivery.

## Prerequisites

Rehearsal:

- Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).
- A checkout of this branch (`feat/photon-denial-alerts` until it merges).

Live only, in addition:

- Node.js ≥ 20.
- `SPECTRUM_PROJECT_ID` and `SPECTRUM_PROJECT_SECRET` exported in the watcher
  terminal (Spectrum > Configure). These are not the REST `PHOTON_API_KEY`.
  Do not paste them into slides, chat, or the repo.
- The recipient iPhone registered on the Photon project. On the Free plan a
  shared iMessage number is enough.
- The bridge installed from the lockfile:

```bash
npm ci --prefix integrations/photon-spectrum
```

That lockfile pins `spectrum-ts` 12.14.0 and `@opentelemetry/core` 2.12.0.
`npm audit` on it reports no vulnerabilities. Details are in
[integrations/photon.md](integrations/photon.md).

## Rehearsal (no network)

From the repository root:

```bash
uv run atp demo photon --out photon-demo
```

`--out` keeps the files so a question can go back to the trace. Omit it to
use a temporary directory.

### What the audience should see

1. **Header.** `DEMO PHOTON` and `transport: dry-run`, `credentials: none`,
   `network: none`, `iMessage: not sent`.
2. **MCP call.** Delegated capabilities are `notes:read` and `notes:write`
   (`notes:destroy` is not delegated). `write_note -> ALLOW` and the upstream
   reports the note was written. `delete_note -> DENY` with
   `CAPABILITY_NOT_GRANTED`, a trace ID, and `note still exists: True`.
   The delete never reached the notes server.
3. **Why.** `atp policy explain` shows `DENY  CAPABILITY_NOT_GRANTED`,
   decided by `capability.required.v1`, and the capability the agent would
   need.
4. **Regression.** `atp regression add` writes `photon-demo/atp-regression.yaml`
   (`ADDED delete stays denied`). `atp test` prints `[PASS] delete stays denied`
   and `1/1 passed under notes-v1`. That is the pin: the suite fails if this
   denial ever flips to ALLOW.
5. **Verified trace.** `atp trace show` prints `integrity: valid` and
   `decision: DENY CAPABILITY_NOT_GRANTED`.
6. **Exact alert text.** A dry run, not a send:

```text
DRY RUN (no Photon request)
AGENT TRUST PLANE
Decision: DENY (enforced)
Trace: <the trace id from step 2>
Reason: CAPABILITY_NOT_GRANTED
ATP withheld authorization. Review the trace locally for details.
Read-only notification. Text replies cannot approve actions.
```

The note body (`buy milk`) is not in that message. The command exits 0.
Nothing in this run contacts Photon or Spectrum.

Say explicitly that this is the text the live path would send, and that the
phone is a separate step.

## Live mode (owner Mac and iPhone)

Use two terminals. Replace `+1...` with the registered number. Do not print
the project secret.

The watcher ignores traces that already exist when it starts, and it claims
each new denial once. Generate the denial **after** the watcher is running.

Terminal A — prepare a home, then watch:

```bash
cd ~/Projects/agent-trust-plane
npm ci --prefix integrations/photon-spectrum
[[ -n "$SPECTRUM_PROJECT_ID" && -n "$SPECTRUM_PROJECT_SECRET" ]] \
  && echo "Spectrum credentials ready"

uv run --python 3.12 atp demo wrap --out photon-live
uv run --python 3.12 atp photon watch \
  --transport spectrum \
  --to +1... \
  --home photon-live/.atp
```

The first lines should be: existing trace history will not be sent, then
that it is watching. Leave this process running.

Terminal B — create a **new** denial in that same home:

```bash
cd ~/Projects/agent-trust-plane
uv run --python 3.12 atp demo wrap --out photon-live
```

### What the audience should see

- Terminal B: the same ALLOW write and DENY delete as the rehearsal, with a
  **new** trace ID.
- Terminal A: `Photon requests accepted: 1; uncertain: 0` (wording includes
  the accepted and uncertain counts). "Accepted" means the Spectrum request
  completed. It does not prove the carrier delivered the iMessage.
- The iPhone: the same five-line alert as the rehearsal, with that new
  trace ID and `CAPABILITY_NOT_GRANTED`.

Stop the watcher with Ctrl+C. It does not retry after an ambiguous outcome,
and it does not read replies.

`--transport rest` remains available and needs different credentials
(`PHOTON_PROJECT_ID`, `PHOTON_API_KEY`, `PHOTON_AGENT_USER_ID`). The default,
and the live path above, is `--transport spectrum`.

## Fallback if the live iMessage does not arrive

Stay on the rehearsal transcript. The dry-run text is the message.

1. If Terminal A says `uncertain`, do not run the watcher again on that
   trace and do not delete `photon-live/.atp/photon-alerts.db`. The claim
   was recorded before the request; a retry can double-send or hide a send
   that already happened. Check the Photon dashboard.
2. If Terminal A never prints a request line, the new denial was likely
   created before the watcher started (it only alerts on traces newer than
   its baseline). Leave the watcher up and run `atp demo wrap --out photon-live`
   once more.
3. If the watcher exits immediately with "no ATP home", run the first
   `atp demo wrap --out photon-live` and start the watcher again.
4. If the error is missing Node, `spectrum-ts`, or Spectrum credentials,
   fix that and use a fresh directory (`photon-live-2`) so a failed claim
   is not reused.
5. One manual send, the path confirmed on device on 2026-10-28, on a trace
   the watcher has not claimed:

```bash
uv run --python 3.12 atp photon notify TRACE_ID \
  --to +1... \
  --home photon-live/.atp \
  --transport spectrum \
  --dry-run
# preview only; remove --dry-run to send once
```

6. If the phone still shows nothing, end on the rehearsal. Do not describe
   the live message as delivered.

## Security boundary (do not widen this on stage)

- Opt-in only. `notify` needs an explicit trace. `watch` must be started
  with a fixed recipient and does not replay history.
- Outbound alert text is limited to status, trace ID, and reason code.
- Invalid trace integrity is not alerted. Shadow-mode `WOULD_DENY` is not
  alerted. Only an enforced `DENY` is.
- No inbound command channel, no approval, no grant change, no effect on
  authorization if Photon is down.
- No automatic retry after an ambiguous transport result.

Full limits: [integrations/photon.md](integrations/photon.md). Threat model:
[security/threat-model.md](security/threat-model.md).
