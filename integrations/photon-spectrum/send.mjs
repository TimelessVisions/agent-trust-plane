/**
 * Outbound iMessage transport, invoked only after ATP's verified-denial gate.
 * The payload is provided over stdin by ATP. No inbound approvals or tools.
 */
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import { telegram } from "spectrum-ts/providers/telegram";

// Existing iMessage CLI remains node send.mjs +12125550123.
// Telegram uses node send.mjs telegram <numeric-telegram-user-id>.
const isTelegram = process.argv[2] === "telegram";
const recipient = isTelegram ? process.argv[3] : process.argv[2];
const projectId = process.env.SPECTRUM_PROJECT_ID;
const projectSecret = process.env.SPECTRUM_PROJECT_SECRET;
if (isTelegram ? !/^[1-9]\d{4,19}$/.test(recipient || "") :
    !/^\+[1-9]\d{7,14}$/.test(recipient || "")) {
  process.stderr.write("Invalid recipient identifier for selected channel\n");
  process.exit(2);
}
if (isTelegram && !process.env.SPECTRUM_TELEGRAM_BOT_TOKEN) {
  process.stderr.write("SPECTRUM_TELEGRAM_BOT_TOKEN is required for Telegram\n");
  process.exit(2);
}
if (!projectId || !projectSecret) {
  process.stderr.write("Missing SPECTRUM_PROJECT_ID or SPECTRUM_PROJECT_SECRET\n");
  process.exit(2);
}
let content = "";
for await (const chunk of process.stdin) {
  content += chunk.toString();
  if (content.length > 4096) {
    process.stderr.write("ATP alert exceeds size limit\n");
    process.exit(2);
  }
}
if (!content.startsWith("AGENT TRUST PLANE\nDecision: DENY (enforced)\n") ||
    !content.includes("\nRead-only notification. Text replies cannot approve actions.")) {
  process.stderr.write("Refusing unexpected ATP alert format\n");
  process.exit(2);
}
let app;
try {
  app = await Spectrum({
    projectId,
    projectSecret,
    providers: [isTelegram
      ? telegram.config({ botToken: process.env.SPECTRUM_TELEGRAM_BOT_TOKEN })
      : imessage.config()],
  });
  const cloud = isTelegram ? telegram(app) : imessage(app);
  const user = await cloud.user(recipient);
  const space = await cloud.space.create(user);
  await space.send(content);
  process.stdout.write("Spectrum send request completed; confirm delivery in the selected channel.\n");
} catch {
  // Do not print SDK exceptions: they may embed secret configuration.
  // No retry: request may have succeeded despite a broken acknowledgement.
  process.stderr.write("Spectrum delivery outcome unknown or rejected; check Photon dashboard.\n");
  process.exitCode = 1;
} finally {
  if (app) {
    try { await app.stop(); } catch {
      process.stderr.write("Spectrum SDK shutdown failed.\n");
    }
  }
}
