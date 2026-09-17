"use client";

import { useCallback, useEffect, useState } from "react";

import {
  api,
  isReport,
  type EvalReport,
  type EvalResult,
  type Health,
  type PolicySetView,
  type ReplayResult,
  type TraceSummary,
  type TraceView,
} from "@/lib/api";

import ArchitectureFlow from "./ArchitectureFlow";
import DecisionPanel from "./DecisionPanel";
import DelegationChain from "./DelegationChain";
import EvalGrid from "./EvalGrid";
import Header from "./Header";
import ReplayPanel from "./ReplayPanel";
import TraceList from "./TraceList";
import TraceTimeline from "./TraceTimeline";

const PRIMARY_EVAL = "EVAL-002";

function describe(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [running, setRunning] = useState(false);
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<TraceView | null>(null);
  const [policySets, setPolicySets] = useState<PolicySetView[]>([]);
  const [replayVersion, setReplayVersion] = useState<string>("");
  const [replaying, setReplaying] = useState(false);
  const [replay, setReplay] = useState<ReplayResult | null>(null);
  // Operator key lives in this tab only (sessionStorage); it is never sent
  // anywhere except as a header on operator-only calls.
  const [operatorKey, setOperatorKeyState] = useState<string>("");
  const setOperatorKey = useCallback((v: string) => {
    setOperatorKeyState(v);
    try {
      sessionStorage.setItem("atp.operatorKey", v);
    } catch {
      /* storage unavailable */
    }
  }, []);
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem("atp.operatorKey");
      if (saved) setOperatorKeyState(saved);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const loadTraces = useCallback(async () => {
    try {
      setTraces(await api.traces(50));
    } catch (e) {
      setError(describe(e));
    }
  }, []);

  const selectTrace = useCallback(async (id: string) => {
    setSelectedId(id);
    setReplay(null);
    try {
      setView(await api.trace(id));
      setError(null);
    } catch (e) {
      setError(describe(e));
    }
  }, []);

  // Initial load: health, policy sets, latest eval report, traces.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, ps, rep] = await Promise.all([api.health(), api.policySets(), api.evalResults()]);
        if (cancelled) return;
        setHealth(h);
        setPolicySets(ps);
        setReplayVersion(ps.find((p) => p.is_default)?.version ?? ps[0]?.version ?? "");
        if (isReport(rep)) {
          setReport(rep);
          const primary = rep.results.find((r) => r.eval_id === PRIMARY_EVAL)?.primary_trace_id;
          if (primary) void selectTrace(primary);
        }
        await loadTraces();
        setError(null);
      } catch (e) {
        if (!cancelled) setError(describe(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadTraces, selectTrace]);

  const runEvals = useCallback(async () => {
    setRunning(true);
    try {
      const rep = await api.runEvals(operatorKey);
      setReport(rep);
      const primary = rep.results.find((r) => r.eval_id === PRIMARY_EVAL)?.primary_trace_id;
      if (primary) await selectTrace(primary);
      await loadTraces();
      setError(null);
    } catch (e) {
      setError(describe(e));
    } finally {
      setRunning(false);
    }
  }, [loadTraces, selectTrace, operatorKey]);

  const onSelectEval = useCallback(
    (r: EvalResult) => {
      if (r.primary_trace_id) void selectTrace(r.primary_trace_id);
    },
    [selectTrace],
  );

  const doReplay = useCallback(async () => {
    if (!selectedId) return;
    setReplaying(true);
    try {
      const res = await api.replay(selectedId, replayVersion || null);
      setReplay(res);
      setView(await api.trace(selectedId));
      await loadTraces();
      setError(null);
    } catch (e) {
      setError(describe(e));
    } finally {
      setReplaying(false);
    }
  }, [selectedId, replayVersion, loadTraces]);

  return (
    <main className="page">
      <Header health={health} error={error} />
      {error && (
        <div className="error-banner">
          Gateway error: <code>{error}</code>. Start it with <code>uv run python -m atp_gateway</code>{" "}
          and make sure <code>NEXT_PUBLIC_ATP_GATEWAY_URL</code> points at it.
        </div>
      )}
      <div className="stack">
        <EvalGrid
          report={report}
          running={running}
          onRun={runEvals}
          selectedTraceId={selectedId}
          onSelect={onSelectEval}
          operatorKey={operatorKey}
          onOperatorKey={setOperatorKey}
        />
        <div className="grid">
          <div className="stack">
            <TraceTimeline view={view} />
            <TraceList traces={traces} selected={selectedId} onSelect={selectTrace} onRefresh={loadTraces} />
          </div>
          <div className="stack">
            <DecisionPanel view={view} />
            <DelegationChain view={view} />
            <ReplayPanel
              view={view}
              policySets={policySets}
              selected={replayVersion}
              onSelect={setReplayVersion}
              onReplay={doReplay}
              busy={replaying}
              result={replay}
            />
          </div>
        </div>
        <ArchitectureFlow view={view} />
      </div>
      <p className="footer-note">
        Every panel reads from the gateway&apos;s append-only, hash-chained trace store. Blocked actions
        are proven blocked by the payments ledger, not by a status flag.
      </p>
    </main>
  );
}
