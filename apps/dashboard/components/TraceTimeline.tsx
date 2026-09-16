import type { TraceView } from "@/lib/api";
import { buildTimeline } from "@/lib/timeline";

export default function TraceTimeline({ view }: { view: TraceView | null }) {
  if (!view) {
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>Trace timeline</h2>
        </div>
        <div className="panel-body muted">Select an eval or a trace to inspect its timeline.</div>
      </section>
    );
  }
  const steps = buildTimeline(view);
  const integrity = view.integrity;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          Trace <span className="trace-id">{view.trace_id.toUpperCase()}</span>
        </h2>
        <span className={`integrity ${integrity.valid ? "mark-ok" : "mark-bad"}`}>
          {integrity.valid ? "hash chain intact" : `chain broken at seq ${integrity.first_bad_seq}`} ·{" "}
          {integrity.event_count} events · head {integrity.head_hash.slice(0, 12)}
        </span>
      </div>
      <ol className="timeline">
        {steps.map((s) => (
          <li key={s.seq}>
            <span className="n">{String(s.index).padStart(2, "0")}</span>
            <div>
              <div className="label">{s.label}</div>
              {s.detail && <div className="detail">{s.detail}</div>}
              <div className="detail dim">
                {s.eventType} · {s.actor}
              </div>
            </div>
            <span className={`glyph mark-${s.mark}`}>{s.glyph}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
