import type { TraceView } from "@/lib/api";

const STAGES = [
  { key: "agent", t: "Agent", s: "proposes an action" },
  { key: "envelope", t: "Action envelope", s: "who · for whom · what · why" },
  { key: "identity", t: "Identity + delegation", s: "chain resolved, authority intersected" },
  { key: "policy", t: "Policy engine", s: "versioned, deterministic" },
  { key: "decision", t: "Allow / Deny / Approval", s: "reason code + matched policy" },
  { key: "execution", t: "Tool execution", s: "signed single-use grant" },
  { key: "audit", t: "Audit + trace", s: "hash-chained, replayable" },
];

export default function ArchitectureFlow({ view }: { view: TraceView | null }) {
  const types = new Set(view?.events.map((e) => e.event_type) ?? []);
  const reached: Record<string, boolean> = {
    agent: types.has("task_received") || types.has("action_proposed"),
    envelope: types.has("action_proposed"),
    identity: types.has("delegation_resolved") || types.has("delegation_resolution_failed"),
    policy: types.has("policy_evaluated"),
    decision: types.has("decision_made"),
    execution: types.has("execution_completed"),
    audit: (view?.events.length ?? 0) > 0,
  };
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Control path</h2>
        <span className="mono muted">
          {view ? "highlighted: stages this trace reached" : "the boundary every consequential action crosses"}
        </span>
      </div>
      <div className="arch">
        {STAGES.map((st, i) => (
          <div key={st.key} style={{ display: "contents" }}>
            <div className={`box ${st.key === "decision" ? "decision" : ""} ${view && reached[st.key] ? "active" : ""}`}>
              <div className="t">{st.t}</div>
              <div className="s">{st.s}</div>
            </div>
            {i < STAGES.length - 1 && <div className="arrow">→</div>}
          </div>
        ))}
      </div>
    </section>
  );
}
