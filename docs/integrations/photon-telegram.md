# ATP × Photon Spectrum — Telegram outbound alerts (experimental)

This feature adds Telegram **direct-message** delivery for ATP's existing verified
enforced DENY notification. It reuses the same minimal alert and cannot grant
permissions, execute actions, or interpret inbound messages.

The working iMessage integration remains unchanged on `feat/photon-denial-alerts`.
This feature is isolated on `feat/telegram-denial-alerts` and must pass CI and
a real Telegram delivery test before it can be considered verified.

## Prerequisites

- An existing Photon Spectrum project: `SPECTRUM_PROJECT_ID` and
  `SPECTRUM_PROJECT_SECRET` in the current terminal environment.
- A Telegram **bot created through [@BotFather](https://t.me/BotFather)**.
  Send `/newbot`, choose a name and unique username, and keep the bot token
  in `SPECTRUM_TELEGRAM_BOT_TOKEN`.
- Open your new bot in Telegram and tap **Start** / send `/start` first.
  Telegram bots generally cannot initiate private chats with users who have
  never started them.
- Use the numeric Telegram user ID, **not your username or phone number**.
  Before the bridge runs for the first time, with `/start` already sent,
  you can identify your own user ID from your bot's update queue:

```bash
python3 - <<'PY'
import json
import os
from urllib.request import urlopen
token = os.environ["SPECTRUM_TELEGRAM_BOT_TOKEN"]
with urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15) as response:
    data = json.load(response)
for update in data.get("result", []):
    msg = update.get("message", {})
    sender = msg.get("from", {})
    if msg.get("text", "").startswith("/start"):
        print("Telegram user ID:", sender.get("id"))
PY
```

This prints only IDs, not tokens. If empty, send /start to your bot and
run it again; a previously registered webhook may also prevent getUpdates.
Do not disable a production bot's webhook or use a third-party ID bot.

## Local test from macOS Terminal

Keep existing project variables in the same shell. In a fresh terminal,
export them again through a secure secret source as needed; variables set
in one Terminal window are not automatically shared with another.

```bash
cd ~/Projects/agent-trust-plane
git fetch origin
git switch feat/telegram-denial-alerts
npm install --prefix integrations/photon-spectrum

# Set this locally: do not commit it or paste it into chat.
export SPECTRUM_TELEGRAM_BOT_TOKEN="YOUR_BOTFATHER_TOKEN"

# First verify ATP only. No message is sent.
uv run --python 3.12 atp photon notify 972d18d90f9e \
  --transport spectrum --channel telegram --to YOUR_NUMERIC_TELEGRAM_USER_ID \
  --home photon-demo/.atp --dry-run

# After reviewing preview, send ONE message.
uv run --python 3.12 atp photon notify 972d18d90f9e \
  --transport spectrum --channel telegram --to YOUR_NUMERIC_TELEGRAM_USER_ID \
  --home photon-demo/.atp
```

A completed request is not proof of delivery. Verify the message is
actually visible in your Telegram chat before proceeding.

## Opt-in automatic notifications

Terminal A:

```bash
uv run --python 3.12 atp photon watch \
  --transport spectrum --channel telegram \
  --to YOUR_NUMERIC_TELEGRAM_USER_ID --home photon-demo/.atp
```

Terminal B, *after* the watcher prints it is initialized:

```bash
uv run --python 3.12 atp demo wrap --out photon-demo
```

The watcher uses `photon-demo/.atp/photon-alerts-telegram.db` so it cannot
interfere with the existing `photon-alerts.db` iMessage state. It skips
historical traces on first startup and will not retry ambiguous sends.
Stop with Ctrl+C.

## Constraints

- Telegram is configured with `telegram.config({botToken})` and
  `telegram(app)`; it uses the Bot API. Photon registers a Fusor webhook
  when the provider starts in cloud mode. No inbound events are processed by
  this alert-only sender.
- **No group or channel notifications**: numeric positive Telegram user IDs
  only, to reduce accidental broad disclosure of security metadata.
- Never send raw trace objects, agent arguments, credentials or private
  explanations over messaging. Only integrity-verified enforced denials pass
  the Python ATP gate.
- Telegram and iMessage have distinct recipient identities, journal files,
  and authorization scopes. A chat account is **not** an authenticated ATP
  operator, and replies **cannot** approve actions.
- Existing Python dependency advisories (#2) and npm audit findings must
  be resolved or reviewed before external production pilots.

Official Spectrum guides:
- https://photon.codes/docs/spectrum-ts/providers/telegram/setup
- https://photon.codes/docs/spectrum-ts/providers/telegram/conversations-and-features
