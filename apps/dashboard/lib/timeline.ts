import type { Decision, TraceEvent, TraceView } from "./api";

export type StepMark = "ok" | "warn" | "bad" | "info";

export interface TimelineStep {
  seq: number;
  index: number;
  label: string;
  detail: string | null;
  mark: StepMark;
  glyph: string;
  actor: string;
  eventType: string;
  ts: string;
}

const GLYPH: Record<StepMark, string> = { ok: "✓", warn: "⚠", bad: "!", info: "·" };

function money(args: Record<string, unknown>): string {
  const a = args["amount"];
  const c = args["currency"];
  return typeof a === "string" && typeof c === "string" ? `${c} ${a}` : "";
}

function step(
  ev: TraceEvent,
  index: number,
  label: string,
  mark: StepMark,
  detail: string | null = null,
): TimelineStep {
  return {
    seq: ev.seq,
    index,
    label,
    detail,
    mark,
    glyph: GLYPH[mark],
    actor: ev.actor,
    eventType: ev.event_type,
    ts: ev.ts,
  };
}

/** Turn raw trace events into the human timeline shown on the dashboard. */
export function buildTimeline(view: TraceView): TimelineStep[] {
  const decision: Decision | null = view.decision;
  const denied = decision?.outcome === "DENY";
  const steps: TimelineStep[] = [];
  let i = 0;

  for (const ev of view.events) {
    i += 1;
    const p = ev.payload;
    switch (ev.event_type) {
      case "task_received":
        steps.push(step(ev, i, "User delegated task", "ok", str(p["task"])));
        break;
      case "external_content_ingested": {
        const src = p["source"] as { trust?: string; kind?: string; origin?: string } | undefined;
        const untrusted = src?.trust === "untrusted";
        steps.push(
          step(
            ev,
            i,
            untrusted ? "External content entered context" : "Content ingested",
            untrusted ? "warn" : "info",
            src ? `${src.kind ?? "content"} · ${src.origin ?? ""} · ${src.trust ?? ""}` : null,
          ),
        );
        break;
      }
      case "identity_rejected": {
        const who = p["authenticated_agent"] as { id?: string } | undefined;
        const claimed = p["claimed_agent"] as { id?: string } | undefined;
        steps.push(
          step(
            ev,
            i,
            "Identity rejected",
            "bad",
            `${who?.id ?? "?"} authenticated but claimed to be ${claimed?.id ?? "?"}`,
          ),
        );
        break;
      }
      case "action_proposed": {
        const env = p["envelope"] as
          | { tool?: string; action?: string; resource?: string; arguments?: Record<string, unknown> }
          | undefined;
        const amount = env?.arguments ? money(env.arguments) : "";
        steps.push(
          step(
            ev,
            i,
            `Agent requested ${env?.tool ?? "tool"}.${env?.action ?? "action"}`,
            denied ? "warn" : "info",
            [env?.resource, amount].filter(Boolean).join(" · ") || null,
          ),
        );
        break;
      }
      case "delegation_resolved": {
        const chain = (p["chain"] as unknown[] | undefined)?.length ?? 0;
        steps.push(step(ev, i, "Authority evaluated", "ok", `${chain}-link delegation chain resolved`));
        break;
      }
      case "delegation_resolution_failed":
        steps.push(step(ev, i, "Authority could not be resolved", "bad", str(p["reason_code"])));
        break;
      case "policy_evaluated": {
        const evals = (p["evaluations"] as { outcome?: string }[] | undefined) ?? [];
        const violations = evals.filter((e) => e.outcome !== "ALLOW").length;
        steps.push(
          violations > 0
            ? step(ev, i, "Policy violation identified", "bad", `${violations} of ${evals.length} policies did not pass`)
            : step(ev, i, "Policies evaluated", "ok", `${evals.length} policies passed`),
        );
        break;
      }
      case "decision_made": {
        const d = p["decision"] as { outcome?: string; reason_code?: string } | undefined;
        const mark: StepMark = d?.outcome === "ALLOW" ? "ok" : d?.outcome === "DENY" ? "bad" : "warn";
        steps.push(step(ev, i, `Decision: ${d?.outcome ?? "?"}`, mark, str(d?.reason_code)));
        break;
      }
      case "approval_requested":
        steps.push(step(ev, i, "Human approval requested", "warn", str(p["approver_role"])));
        break;
      case "grant_issued":
        steps.push(step(ev, i, "Single-use execution grant issued", "ok", `expires ${str(p["expires_at"])}`));
        break;
      case "execution_attempted":
        steps.push(
          step(
            ev,
            i,
            "Agent attempted execution",
            p["grant_presented"] ? "info" : "warn",
            p["grant_presented"] ? "grant presented" : "no grant presented",
          ),
        );
        break;
      case "execution_blocked":
        steps.push(step(ev, i, "Tool execution blocked", "ok", str(p["reason_code"])));
        break;
      case "execution_completed":
        steps.push(step(ev, i, "Tool executed", "ok", str((p["result"] as { status?: string } | undefined)?.status)));
        break;
      case "execution_failed":
        steps.push(step(ev, i, "Tool execution failed", "bad", str(p["reason_code"])));
        break;
      case "replay_performed":
        steps.push(
          step(ev, i, "Replay performed", p["outcome_changed"] ? "warn" : "info", str(p["summary"])),
        );
        break;
      default:
        steps.push(step(ev, i, ev.event_type, "info"));
    }
  }
  return steps;
}

function str(v: unknown): string | null {
  return typeof v === "string" ? v : v == null ? null : JSON.stringify(v);
}
