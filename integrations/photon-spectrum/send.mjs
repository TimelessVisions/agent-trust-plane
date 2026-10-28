/**
 * Outbound iMessage transport, invoked only after ATP's verified-denial gate.
 * The payload is provided over stdin by ATP. No inbound approvals or tools.
 */
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

const phone = process.argv[2];
const projectId = process.env.SPECTRUM_PROJECT_ID;
const projectSecret = process.env.SPECTRUM_PROJECT_SECRET;
if (!/^\+[1-9]\d{7,14}$/.test(phone || "")) {
  process.stderr.write("Invalid E.164 recipient number\n");
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
    providers: [imessage.config()],
  });
  const cloud = imessage(app);
  const user = await cloud.user(phone);
  const space = await cloud.space.create(user);
  await space.send(content);
  process.stdout.write("Spectrum send request completed; confirm delivery on device.\n");
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
