import type { Health } from "@/lib/api";
import { GATEWAY_URL } from "@/lib/api";

export default function Header({ health, error }: { health: Health | null; error: string | null }) {
  return (
    <header className="header">
      <div>
        <div className="brand">Agent Trust Plane</div>
        <h1 className="title">Agent Production Readiness</h1>
        <p className="subtitle">
          Models propose actions. Independent infrastructure decides whether they execute. Every
          decision below was produced by the live gateway, not a fixture.
        </p>
      </div>
      <div className="status-pills">
        <span className={`pill ${health ? "ok" : error ? "bad" : ""}`}>
          <span className="dot" />
          gateway {health ? "online" : error ? "unreachable" : "connecting"}
        </span>
        {health && (
          <>
            <span className="pill">policy {health.default_policy_set}</span>
            <span className="pill">grant ttl {health.grant_ttl_seconds}s</span>
          </>
        )}
        <span className="pill" title={GATEWAY_URL}>
          {GATEWAY_URL.replace(/^https?:\/\//, "")}
        </span>
      </div>
    </header>
  );
}
