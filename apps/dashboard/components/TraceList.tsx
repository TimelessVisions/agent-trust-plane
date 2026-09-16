import type { TraceSummary } from "@/lib/api";

export default function TraceList({
  traces,
  selected,
  onSelect,
  onRefresh,
}: {
  traces: TraceSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Recent traces</h2>
        <button onClick={onRefresh}>Refresh</button>
      </div>
      <div className="trace-list">
        {traces.length === 0 && <div className="panel-body muted">No traces yet.</div>}
        {traces.map((t) => (
          <button
            key={t.trace_id}
            className={t.trace_id === selected ? "selected" : ""}
            onClick={() => onSelect(t.trace_id)}
          >
            <span>{t.trace_id}</span>
            <span className="last">{t.last_event_type}</span>
            <span className="dim">{t.event_count} ev</span>
          </button>
        ))}
      </div>
    </section>
  );
}
