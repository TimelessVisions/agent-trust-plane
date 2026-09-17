/** Typed client for the trust gateway. Mirrors the pydantic models on the wire. */

export const GATEWAY_URL =
  process.env.NEXT_PUBLIC_ATP_GATEWAY_URL ?? "http://127.0.0.1:8000";

export type Outcome = "ALLOW" | "DENY" | "REQUIRE_APPROVAL";

export interface PrincipalRef {
  id: string;
  kind: "human" | "agent" | "service";
}

export interface Money {
  amount: string;
  currency: string;
}

export interface PolicyRef {
  id: string;
  version: string;
}

export interface ConstraintEvaluation {
  name: string;
  requested: unknown;
  limit: unknown;
  satisfied: boolean;
  detail: string | null;
}

export interface PolicyEvaluation {
  policy: PolicyRef;
  outcome: Outcome;
  reason_code: string;
  message: string;
  constraints: ConstraintEvaluation[];
}

export interface EffectiveAuthority {
  root_principal: PrincipalRef;
  holder: PrincipalRef;
  grant_chain: string[];
  capabilities: string[];
  resource_scope: string[];
  constraints: { max_amount: Money | null; currencies: string[] | null };
  expires_at: string;
}

export interface Decision {
  decision_id: string;
  trace_id: string;
  envelope_id: string;
  action_hash: string;
  decided_at: string;
  outcome: Outcome;
  reason_code: string;
  explanation: string;
  matched_policy: PolicyRef | null;
  policy_set_version: string;
  evaluations: PolicyEvaluation[];
  effective_authority: EffectiveAuthority | null;
  approval: { approver_role: string; reason: string } | null;
  replay_of: string | null;
}

export interface ContentSource {
  source_id: string;
  kind: string;
  origin: string;
  trust: "trusted" | "untrusted";
  content_hash: string;
  excerpt: string | null;
}

export interface Envelope {
  envelope_id: string;
  trace_id: string;
  issued_at: string;
  principal: PrincipalRef;
  agent: PrincipalRef;
  delegation_grant_id: string;
  capability: string;
  tool: string;
  action: string;
  resource: string;
  arguments: Record<string, unknown>;
  provenance: {
    task_id: string | null;
    task_description: string | null;
    content_sources: ContentSource[];
    model: string | null;
    agent_rationale: string | null;
  };
}

export interface TraceEvent {
  seq: number;
  trace_id: string;
  event_type: string;
  ts: string;
  actor: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface ChainLink {
  grant_id: string;
  label: string;
  grantor: PrincipalRef;
  grantee: PrincipalRef;
  capabilities: string[];
  resource_scope: string[];
  constraints: { max_amount: Money | null; currencies: string[] | null };
  expires_at: string;
}

export interface TraceView {
  trace_id: string;
  events: TraceEvent[];
  integrity: {
    valid: boolean;
    event_count: number;
    head_hash: string;
    first_bad_seq: number | null;
    detail: string | null;
  };
  envelope: Envelope | null;
  decision: Decision | null;
  delegation_chain: ChainLink[];
  execution: Record<string, unknown> | null;
  replays: Record<string, unknown>[];
}

export interface TraceSummary {
  trace_id: string;
  started_at: string;
  last_event_at: string;
  event_count: number;
  last_event_type: string;
  head_hash: string;
}

export interface Check {
  name: string;
  passed: boolean;
  expected: unknown;
  observed: unknown;
  detail: string | null;
}

export interface EvalResult {
  eval_id: string;
  title: string;
  threat: string;
  description: string;
  status: "PASS" | "FAIL" | "ERROR";
  checks: Check[];
  explanation: string;
  trace_ids: string[];
  primary_trace_id: string | null;
  decision: Decision | null;
  error: string | null;
  duration_ms: number;
}

export interface EvalReport {
  run_id: string;
  started_at: string;
  finished_at: string;
  gateway: Record<string, unknown>;
  results: EvalResult[];
}

export interface Health {
  status: string;
  default_policy_set: string;
  grant_ttl_seconds: number;
  tools: string[];
  signing_key_fingerprint: string;
}

export interface PolicySetView {
  version: string;
  description: string;
  is_default: boolean;
  policies: PolicyRef[];
  policy_descriptions: Record<string, string>;
}

export interface ReplayResult {
  trace_id: string;
  original_decision: Decision;
  replayed_decision: Decision;
  original_policy_set_version: string;
  replayed_policy_set_version: string;
  outcome_changed: boolean;
  summary: string;
}

export class GatewayError extends Error {
  constructor(
    public status: number,
    public reasonCode: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${GATEWAY_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let body: { reason_code?: string; message?: string; detail?: unknown } = {};
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new GatewayError(
      res.status,
      body.reason_code ?? "HTTP_ERROR",
      body.message ?? (typeof body.detail === "string" ? body.detail : res.statusText),
    );
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  policySets: () => request<PolicySetView[]>("/policy-sets"),
  traces: (limit = 50) => request<TraceSummary[]>(`/traces?limit=${limit}`),
  trace: (id: string) => request<TraceView>(`/traces/${id}`),
  ledger: () => request<Record<string, unknown>[]>("/ledger/payments"),
  evalResults: () => request<EvalReport | { status: "never_run"; results: [] }>("/evals/results"),
  /** Operator-only. The key is sent as a header and never stored server-side or logged. */
  runEvals: (operatorKey: string) =>
    request<EvalReport>("/evals/run", {
      method: "POST",
      headers: { "X-ATP-Operator-Key": operatorKey },
    }),
  replay: (id: string, policySetVersion: string | null) =>
    request<ReplayResult>(`/replay/${id}`, {
      method: "POST",
      body: JSON.stringify({ policy_set_version: policySetVersion }),
    }),
};

export function isReport(x: unknown): x is EvalReport {
  return typeof x === "object" && x !== null && "run_id" in x;
}
