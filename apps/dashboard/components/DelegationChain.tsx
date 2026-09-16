import type { Money, TraceView } from "@/lib/api";

function limit(m: Money | null): string {
  if (!m) return "no monetary limit";
  return `≤ ${m.currency} ${Number(m.amount).toLocaleString("en-US")}`;
}

export default function DelegationChain({ view }: { view: TraceView | null }) {
  const chain = view?.delegation_chain ?? [];
  const failed = view?.events.find((e) => e.event_type === "delegation_resolution_failed");
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Delegation chain</h2>
        <span className="mono muted">
          {chain.length ? "effective authority = intersection" : failed ? "unresolved" : ""}
        </span>
      </div>
      {failed && (
        <div className="panel-body">
          <div className="mark-bad mono">{String(failed.payload["reason_code"])}</div>
          <div className="muted">{String(failed.payload["message"])}</div>
        </div>
      )}
      {chain.length > 0 && (
        <div className="chain">
          {chain.map((link, i) => (
            <div className="link" key={link.grant_id}>
              <div className="rail">
                <span className={`node ${link.grantee.kind}`} />
                {i < chain.length - 1 && <span className="wire" />}
              </div>
              <div>
                <div className="who">
                  {link.grantee.id}
                  <span className="kind">{link.grantee.kind}</span>
                </div>
                <div className="grant">
                  <b>{link.label}</b>
                  <br />
                  {link.capabilities.join(", ")} · {link.resource_scope.join(", ")} ·{" "}
                  {limit(link.constraints.max_amount)}
                  <br />
                  <span className="dim">
                    {link.grant_id.slice(0, 14)}… · expires {new Date(link.expires_at).toISOString().slice(0, 16)}Z
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {!failed && chain.length === 0 && (
        <div className="panel-body muted">No delegation was resolved on this trace.</div>
      )}
    </section>
  );
}
