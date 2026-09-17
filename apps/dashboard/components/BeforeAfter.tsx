import type { Decision, PolicySetView, ReplayResult, TraceView } from "@/lib/api";

type LedgerRow = Record<string, unknown>;

function qualified(p: { id: string; version: string } | null | undefined): string | null {
  return p ? `${p.id}.${p.version}` : null;
}

function Side({
  label,
  policySet,
  decision,
}: {
  label: string;
  policySet: string;
  decision: Decision | { outcome: string; reason_code: string; matched_policy: { id: string; version: string } | null } | null;
}) {
  return (
    <div className="side">
      <div className="mono dim" style={{ fontSize: 11 }}>
        {label} · {policySet}
      </div>
      {decision ? (
        <>
          <div className={`oc ${decision.outcome}`}>{decision.outcome}</div>
          <div className="mono muted" style={{ fontSize: 12 }}>
            {decision.reason_code}
          </div>
          <div className="mono dim" style={{ fontSize: 11 }}>
            {qualified(decision.matched_policy) ?? "no policy matched"}
          </div>
        </>
      ) : (
        <div className="muted">—</div>
      )}
    </div>
  );
}

export default function BeforeAfter({
  view,
  policySets,
  selected,
  onSelect,
  onReplay,
  busy,
  result,
  ledger,
}: {
  view: TraceView | null;
  policySets: PolicySetView[];
  selected: string;
  onSelect: (v: string) => void;
  onReplay: () => void;
  busy: boolean;
  result: ReplayResult | null;
  ledger: LedgerRow[];
}) {
  const original = view?.decision ?? null;
  const env = view?.envelope ?? null;
  // Prefer a fresh replay result; otherwise the last replay recorded on the trace.
  const recorded = view?.replays.length ? view.replays[view.replays.length - 1] : null;
  const after =
    result && result.trace_id === view?.trace_id
      ? { decision: result.replayed_decision, policySet: result.replayed_policy_set_version }
      : recorded
        ? {
            decision: recorded["replayed_decision"] as Decision,
            policySet: String(recorded["replayed_policy_set_version"]),
          }
        : null;
  const beforeSet = original?.policy_set_version ?? "";
  const afterSet = after?.policySet ?? selected;
  const beforePolicies = new Set(
    policySets.find((p) => p.version === beforeSet)?.policies.map((p) => `${p.id}.${p.version}`) ?? [],
  );
  const afterPolicies = new Set(
    policySets.find((p) => p.version === afterSet)?.policies.map((p) => `${p.id}.${p.version}`) ?? [],
  );
  const added = [...afterPolicies].filter((p) => !beforePolicies.has(p));
  const removed = [...beforePolicies].filter((p) => !afterPolicies.has(p));
  const rows = view ? ledger.filter((r) => r["trace_id"] === view.trace_id) : [];
  const changed = original && after ? original.outcome !== after.decision.outcome : null;
  const args = env?.arguments ?? {};

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Before / after</h2>
        <span className="mono muted">recorded action · replayed under another policy set</span>
      </div>
      {!view || !original || !env ? (
        <div className="panel-body muted">Select a trace with a recorded decision.</div>
      ) : (
        <div className="panel-body">
          <div className="mono" style={{ marginBottom: 10 }}>
            {env.tool}.{env.action} on {env.resource}
            {typeof args["amount"] === "string" ? ` · ${String(args["currency"])} ${String(args["amount"])}` : ""}
            {typeof args["destination_account"] === "string" ? ` → ${String(args["destination_account"])}` : ""}
          </div>
          <div className="replay-diff">
            <Side label="before" policySet={beforeSet} decision={original} />
            <div className="arrow">→</div>
            <Side label="after" policySet={afterSet} decision={after?.decision ?? null} />
          </div>
          {changed !== null && (
            <div className={`changed ${changed ? "mark-warn" : "mark-ok"}`}>
              {changed
                ? "outcome changed — the policy change alters this recorded decision"
                : "outcome unchanged — the decision is reproducible under this policy set"}
            </div>
          )}
          <dl className="kv" style={{ padding: "12px 0 0" }}>
            <dt>Policy diff</dt>
            <dd className="mono">
              {added.length === 0 && removed.length === 0 && <span className="dim">same policy set</span>}
              {added.map((p) => (
                <div key={p} className="mark-ok">
                  + {p}
                </div>
              ))}
              {removed.map((p) => (
                <div key={p} className="mark-bad">
                  − {p}
                </div>
              ))}
            </dd>
            <dt>Authority</dt>
            <dd className="mono">
              {original.effective_authority
                ? `${original.effective_authority.holder.id} · ${
                    original.effective_authority.constraints.max_amount
                      ? `≤ ${original.effective_authority.constraints.max_amount.currency} ${original.effective_authority.constraints.max_amount.amount}`
                      : "no monetary limit"
                  } · ${original.effective_authority.grant_chain.length}-link chain`
                : "unresolved"}
            </dd>
            <dt>Side effects</dt>
            <dd className="mono">
              {rows.length === 0 ? (
                <span>none — nothing on the ledger for this trace</span>
              ) : (
                rows.map((r, i) => (
                  <div key={i} className="mark-warn">
                    settled {String(r["currency"])} {String(r["amount"])} → {String(r["destination_account"])}{" "}
                    <span className="dim">(this happened under {beforeSet}; replay cannot undo it)</span>
                  </div>
                ))
              )}
            </dd>
            <dt>Replay is</dt>
            <dd className="muted">
              a re-evaluation of the recorded envelope against the recorded delegation snapshot. It does
              not rerun the agent, re-read the invoice, or execute anything.
            </dd>
          </dl>
          <div className="replay-row" style={{ marginTop: 12 }}>
            <span className="muted">Replay under</span>
            <select value={selected} onChange={(e) => onSelect(e.target.value)}>
              {policySets.map((p) => (
                <option key={p.version} value={p.version}>
                  {p.version}
                  {p.is_default ? " (active)" : ""}
                </option>
              ))}
            </select>
            <button className="primary" onClick={onReplay} disabled={busy}>
              {busy ? "Replaying…" : "Replay recorded action"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
