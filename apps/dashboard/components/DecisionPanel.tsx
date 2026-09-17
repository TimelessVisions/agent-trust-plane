import type { Money, TraceView } from "@/lib/api";

function fmt(m: Money | null | undefined): string {
  if (!m) return "n/a";
  const n = Number(m.amount);
  return `${m.currency} ${Number.isFinite(n) ? n.toLocaleString("en-US", { minimumFractionDigits: 2 }) : m.amount}`;
}

function requested(args: Record<string, unknown>): Money | null {
  const a = args["amount"];
  const c = args["currency"];
  return typeof a === "string" && typeof c === "string" ? { amount: a, currency: c } : null;
}

export default function DecisionPanel({ view }: { view: TraceView | null }) {
  const d = view?.decision ?? null;
  const env = view?.envelope ?? null;
  if (!view || !d || !env) {
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>Authorization decision</h2>
        </div>
        <div className="panel-body muted">No decision recorded on this trace.</div>
      </section>
    );
  }
  const req = requested(env.arguments);
  const limit = d.effective_authority?.constraints.max_amount ?? null;
  const over = !!(req && limit && Number(req.amount) > Number(limit.amount));
  const executed = view.execution?.["event_type"] === "execution_completed";
  const headline =
    d.outcome === "DENY"
      ? `${fmt(req)} ${env.action.replace("_", " ")} attempt`
      : d.outcome === "ALLOW"
        ? `${fmt(req)} ${env.action.replace("_", " ")} ${executed ? "executed" : "authorized"}`
        : `${fmt(req)} ${env.action.replace("_", " ")} awaiting approval`;
  const destination = env.arguments["destination_account"];

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Authorization decision</h2>
        <span className="mono muted">{d.policy_set_version}</span>
      </div>
      <div className="verdict">
        <div className={`outcome ${d.outcome}`}>
          {d.enforcement === "shadow" && d.outcome !== "ALLOW"
            ? `WOULD ${d.outcome === "DENY" ? "BLOCK" : "HOLD"} (shadow mode; not enforced)`
            : d.outcome === "DENY"
              ? "BLOCKED"
              : d.outcome === "ALLOW"
                ? "ALLOWED"
                : "HELD"}
        </div>
        <div className="headline">{headline}</div>
        <div className="reason">{d.explanation}</div>
      </div>
      <div className="compare">
        <div className="box">
          <div className="cap">Requested</div>
          <div className={`val ${over ? "over" : "ok"}`}>{fmt(req)}</div>
          {typeof destination === "string" && (
            <div className="mono dim" style={{ fontSize: 11 }}>
              → {destination}
            </div>
          )}
        </div>
        <div className="box">
          <div className="cap">Authorized maximum</div>
          <div className="val">{fmt(limit)}</div>
          <div className="mono dim" style={{ fontSize: 11 }}>
            {d.effective_authority ? `${d.effective_authority.grant_chain.length}-link chain` : "unresolved"}
          </div>
        </div>
      </div>
      <dl className="kv">
        <dt>Decision</dt>
        <dd className="mono">{d.outcome}</dd>
        <dt>Reason code</dt>
        <dd className="mono">{d.reason_code}</dd>
        <dt>Matched policy</dt>
        <dd className="mono">{d.matched_policy ? `${d.matched_policy.id}.${d.matched_policy.version}` : "—"}</dd>
        <dt>Agent</dt>
        <dd className="mono">{env.agent.id}</dd>
        <dt>Acting for</dt>
        <dd className="mono">{env.principal.id}</dd>
        <dt>Requested action</dt>
        <dd className="mono">
          {env.tool}.{env.action} on {env.resource} · needs {env.capability}
        </dd>
        <dt>Execution</dt>
        <dd className="mono">
          {view.execution
            ? `${String(view.execution["event_type"])}${view.execution["reason_code"] ? ` · ${String(view.execution["reason_code"])}` : ""}`
            : "not attempted"}
        </dd>
        {env.provenance.content_sources.length > 0 && (
          <>
            <dt>Influenced by</dt>
            <dd className="mono">
              {env.provenance.content_sources.map((s) => (
                <div key={s.source_id}>
                  {s.kind} {s.source_id} ·{" "}
                  <span className={s.trust === "untrusted" ? "mark-warn" : "mark-ok"}>{s.trust}</span> ·{" "}
                  {s.content_hash.slice(0, 12)}
                </div>
              ))}
            </dd>
          </>
        )}
        {env.provenance.agent_rationale && (
          <>
            <dt>Agent rationale</dt>
            <dd className="muted">{env.provenance.agent_rationale}</dd>
          </>
        )}
        <dt>Decision id</dt>
        <dd className="mono dim">{d.decision_id}</dd>
      </dl>
      <table className="evals-table">
        <tbody>
          {d.evaluations.map((e) => (
            <tr key={`${e.policy.id}.${e.policy.version}`}>
              <td>
                {e.policy.id}.{e.policy.version}
              </td>
              <td className={e.outcome === "ALLOW" ? "mark-ok" : e.outcome === "DENY" ? "mark-bad" : "mark-warn"}>
                {e.outcome === "ALLOW" ? "pass" : e.reason_code}
              </td>
              <td className="muted">{e.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
