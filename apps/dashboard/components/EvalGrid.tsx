import type { EvalReport, EvalResult } from "@/lib/api";

const CATALOG: { id: string; title: string; threat: string }[] = [
  { id: "EVAL-001", title: "Normal authorized tool call", threat: "baseline" },
  { id: "EVAL-002", title: "Indirect prompt injection", threat: "indirect prompt injection" },
  { id: "EVAL-003", title: "Privilege escalation", threat: "privilege escalation" },
  { id: "EVAL-004", title: "Excessive monetary authorization", threat: "excessive delegation" },
  { id: "EVAL-005", title: "Compromised child agent", threat: "compromised child agent" },
  { id: "EVAL-006", title: "Under-limit redirect + replay", threat: "evasive injection" },
  { id: "EVAL-007", title: "Modified action after authorization", threat: "confused deputy" },
  { id: "EVAL-008", title: "Execution grant replay", threat: "replay attack" },
];

export default function EvalGrid({
  report,
  running,
  onRun,
  selectedTraceId,
  onSelect,
}: {
  report: EvalReport | null;
  running: boolean;
  onRun: () => void;
  selectedTraceId: string | null;
  onSelect: (result: EvalResult) => void;
}) {
  const byId = new Map((report?.results ?? []).map((r) => [r.eval_id, r]));
  const passed = report ? report.results.filter((r) => r.status === "PASS").length : 0;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Adversarial evals</h2>
        <div className="replay-row">
          <span className="mono muted">
            {report
              ? `${passed}/${report.results.length} passed · run ${report.run_id.slice(-8)}`
              : "never run against this gateway"}
          </span>
          <button className="primary" onClick={onRun} disabled={running}>
            {running ? "Running…" : "Run eval suite"}
          </button>
        </div>
      </div>
      <div className="eval-grid">
        {CATALOG.map((c) => {
          const r = byId.get(c.id);
          const selected = !!r?.primary_trace_id && r.primary_trace_id === selectedTraceId;
          return (
            <button
              key={c.id}
              className={`eval-card ${selected ? "selected" : ""}`}
              onClick={() => r && onSelect(r)}
              disabled={!r}
              title={r?.explanation ?? "Run the suite to produce a trace"}
            >
              <span className="id">
                <span>{c.id}</span>
                <span className={`badge ${r ? r.status : "NEVER"}`}>{r ? r.status : "—"}</span>
              </span>
              <span className="name">{r?.title ?? c.title}</span>
              <span className="threat">{r?.threat ?? c.threat}</span>
              {r && (
                <span className="mono dim" style={{ fontSize: 11 }}>
                  {r.checks.filter((k) => k.passed).length}/{r.checks.length} checks · trace{" "}
                  {r.primary_trace_id ?? "—"}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
