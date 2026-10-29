const $ = (id) => document.getElementById(id);

function setCard(id, className, verdict) {
  const card = $(id);
  card.className = `moment ${className}`;
  card.querySelector(".verdict").textContent = verdict;
}

function focusStageIfRequested() {
  if (new URLSearchParams(window.location.search).get("focus") === "stage") {
    document.querySelector(".stage").scrollIntoView({ block: "start" });
  }
}

function render(data) {
  if (!data || !data.ok) return;
  const write = data.write;
  const denial = data.denial;
  setCard("write-card", "allowed", "ALLOWED + EXECUTED");
  setCard("delete-card", "denied", "DENIED + STOPPED");
  setCard("evidence-card", "proven", "INTEGRITY VALID");
  $("evidence-title").textContent = denial.reason_code.replaceAll("_", " ");
  $("trace").textContent = `Trace ${denial.trace_id} · ${denial.enforcement.toUpperCase()} · head ${denial.head_hash.slice(0, 12)}…`;

  const alert = denial.photon_request;
  if (alert === "accepted") {
    setCard("phone-card", "proven", "REQUEST ACCEPTED");
    $("phone-detail").textContent = "Photon accepted the outbound request — confirm actual delivery on the iPhone";
  } else if (alert === "unknown") {
    setCard("phone-card", "pending", "OUTCOME UNCERTAIN");
    $("phone-detail").textContent = "No automatic retry; reconcile in Photon and on the device";
  } else {
    setCard("phone-card", "pending", "WATCHER OPTIONAL");
    $("phone-detail").textContent = "Start the outbound watcher before the run; replies can never authorize";
  }
  $("event-count").textContent = denial.event_count;
  $("note-state").textContent = data.checks.note_still_exists ? "STILL EXISTS" : "MISSING";
  $("regression-state").textContent = data.checks.regression_pinned ? "YES" : "NO";
  $("facts").hidden = false;
  $("transcript").textContent = data.transcript.join("\n");
  focusStageIfRequested();
}

async function run() {
  const button = $("run");
  button.disabled = true;
  $("progress").hidden = false;
  $("error").hidden = true;
  for (const id of ["write-card", "delete-card", "evidence-card", "phone-card"]) setCard(id, "neutral", "RUNNING");
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "The live demo did not pass every proof check");
    render(data);
  } catch (error) {
    $("error").textContent = `${error.message}. Open Technical evidence for details, then use the event fallback runbook.`;
    $("error").hidden = false;
    try {
      const status = await fetch("/api/status").then((r) => r.json());
      if (status.last?.transcript) $("transcript").textContent = status.last.transcript.join("\n");
    } catch (_) {}
  } finally {
    button.disabled = false;
    $("progress").hidden = true;
  }
}

$("run").addEventListener("click", run);
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !$("run").disabled) run();
});

fetch("/api/status").then((r) => r.json()).then((status) => render(status.last)).catch(() => {});
