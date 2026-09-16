import type { PolicySetView, ReplayResult, TraceView } from "@/lib/api";

export default function ReplayPanel({
  view,
  policySets,
  selected,
  onSelect,
  onReplay,
  busy,
  result,
}: {
  view: TraceView | null;
  policySets: PolicySetView[];
  selected: string;
  onSelect: (v: string) => void;
  onReplay: () => void;
  busy: boolean;
  result: ReplayResult | null;
}) {
  const canReplay = !!view?.decision;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Replay</h2>
        <span className="mono muted">re-evaluate · never executes</span>
      </div>
      <div className="panel-body">
        <div className="replay-row">
          <span className="muted">Rerun the recorded action under</span>
          <select value={selected} onChange={(e) => onSelect(e.target.value)} disabled={!canReplay}>
            {policySets.map((p) => (
              <option key={p.version} value={p.version}>
                {p.version}
                {p.is_default ? " (active)" : ""}
              </option>
            ))}
          </select>
          <button onClick={onReplay} disabled={!canReplay || busy}>
            {busy ? "Replaying…" : "Replay trace"}
          </button>
        </div>
        {policySets.length > 0 && (
          <div className="dim" style={{ marginTop: 8, fontSize: 12 }}>
            {policySets.find((p) => p.version === selected)?.description}
          </div>
        )}
        {result && result.trace_id === view?.trace_id && (
          <>
            <div className="replay-diff">
              <div className="side">
                <div className="mono dim" style={{ fontSize: 11 }}>
                  original · {result.original_policy_set_version}
                </div>
                <div className={`oc ${result.original_decision.outcome}`}>{result.original_decision.outcome}</div>
                <div className="mono muted" style={{ fontSize: 12 }}>
                  {result.original_decision.reason_code}
                </div>
              </div>
              <div className="arrow">→</div>
              <div className="side">
                <div className="mono dim" style={{ fontSize: 11 }}>
                  replayed · {result.replayed_policy_set_version}
                </div>
                <div className={`oc ${result.replayed_decision.outcome}`}>{result.replayed_decision.outcome}</div>
                <div className="mono muted" style={{ fontSize: 12 }}>
                  {result.replayed_decision.reason_code}
                </div>
              </div>
            </div>
            <div className={`changed ${result.outcome_changed ? "mark-warn" : "mark-ok"}`}>
              {result.outcome_changed
                ? "outcome changed — the policy change alters this decision"
                : "outcome unchanged — decision is reproducible under this policy set"}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
