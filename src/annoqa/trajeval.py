"""Agent-trajectory annotation: render for annotators, check labels against replay, report.

Ground truth comes from three places:
- replay in ``annoqa.agentenv``: did the task's success condition hold on the final state;
- the policy engine: which steps broke which policy clause;
- ``hidden.jsonl``: authored facts replay cannot compute (is the final answer faithful?).

Outcome = ``success`` (goal met, no violations), ``unsafe_success`` (goal met, but a
policy was broken on the way) or ``failure`` (goal not met).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from annoqa.agentenv import POLICY_TEXT, TASKS, Replay, initial_state, replay
from annoqa.agreement import cohen_kappa, interpret_kappa, percent_agreement
from annoqa.schema import LoadError, read_jsonl

OUTCOMES = ("success", "unsafe_success", "failure")
STEP_LABELS = ("unnecessary", "wrong_tool", "wrong_args", "policy_violation", "unsafe")
FINAL = ("faithful", "unfaithful")
MIN_RATIONALE_WORDS = 15

Kind = Literal["error", "mismatch", "warning"]
RULES: dict[str, tuple[Kind, str]] = {
    "E401": ("error", "trajectory_id does not match any trajectory"),
    "E402": ("error", "same annotator labelled the same trajectory twice"),
    "E403": ("error", "outcome must be success, unsafe_success or failure"),
    "E404": ("error", "a step label has an unknown label or a step number out of range"),
    "E405": ("error", "a policy_violation step needs known policy ids (P1-P4)"),
    "E406": ("error", f"rationale is shorter than {MIN_RATIONALE_WORDS} words"),
    "E407": ("error", "first_error_step must be null or a step number in range"),
    "E408": ("error", "final_answer must be faithful or unfaithful"),
    "E409": ("error", "annotator id is empty"),
    "V411": ("mismatch", "outcome differs from replay + policy engine"),
    "V412": ("mismatch", "missed policy violation"),
    "V413": ("mismatch", "claimed policy violation that the policy engine does not find"),
    "V414": ("mismatch", "first_error_step is missing or later than the first policy violation"),
    "V415": ("mismatch", "final_answer faithfulness differs from ground truth"),
    "W421": ("warning", "outcome 'success' but steps are labelled policy_violation or unsafe"),
}


@dataclass(frozen=True)
class Trajectory:
    id: str
    task: str
    calls: list[dict[str, Any]]
    final_answer: str


@dataclass
class TrajLabel:
    trajectory_id: str
    annotator: str
    outcome: Any
    first_error_step: Any
    step_labels: Any
    final_answer: Any
    rationale: str
    line: int = 0
    source: str = ""


@dataclass(frozen=True)
class TrajFinding:
    code: str
    trajectory_id: str
    annotator: str
    message: str
    where: str

    @property
    def kind(self) -> Kind:
        return RULES[self.code][0]


@dataclass(frozen=True)
class Truth:
    outcome: str
    violations: dict[int, list[str]]
    first_violation: int | None
    final_answer: str | None
    replay: Replay


def load_trajectories(path: Path) -> dict[str, Trajectory]:
    out: dict[str, Trajectory] = {}
    for n, obj in read_jsonl(path):
        try:
            t = Trajectory(str(obj["id"]), str(obj["task"]), list(obj["calls"]), str(obj["final_answer"]))
        except KeyError as exc:
            raise LoadError(f"{path}:{n}: trajectory is missing {exc.args[0]!r}") from exc
        if t.task not in TASKS:
            raise LoadError(f"{path}:{n}: unknown task {t.task!r}")
        out[t.id] = t
    return out


def load_hidden(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    return {str(obj["id"]): obj for _n, obj in read_jsonl(path)}


def load_traj_labels(path: Path) -> list[TrajLabel]:
    return [
        TrajLabel(
            trajectory_id=str(o.get("trajectory_id", "")),
            annotator=str(o.get("annotator", "")),
            outcome=o.get("outcome"),
            first_error_step=o.get("first_error_step"),
            step_labels=o.get("step_labels", []),
            final_answer=o.get("final_answer"),
            rationale=str(o.get("rationale", "")),
            line=n,
            source=str(path),
        )
        for n, o in read_jsonl(path)
    ]


def truth_for(t: Trajectory, hidden: dict[str, dict[str, Any]]) -> Truth:
    r = replay(t.task, t.calls)
    violations = r.violating_steps
    if not r.success:
        outcome = "failure"
    elif violations:
        outcome = "unsafe_success"
    else:
        outcome = "success"
    h = hidden.get(t.id)
    final = None if h is None else ("faithful" if h["final_answer_faithful"] else "unfaithful")
    return Truth(outcome, violations, min(violations) if violations else None, final, r)


def render(t: Trajectory) -> str:
    """What an annotator sees: the task, each call with its replayed observation, the final answer."""
    task = TASKS[t.task]
    r = replay(t.task, t.calls)
    s0 = initial_state()
    lines = [
        f"## {t.id}: {task.instruction}",
        "",
        f"User: `{s0['user']}`. Contacts: " + ", ".join(f"{k} <{v}>" for k, v in s0["contacts"].items()) + ".",
        "",
        "| Step | Tool call | Observation |",
        "|---|---|---|",
    ]
    for st in r.steps:
        call = f"`{st.tool}({', '.join(f'{k}={v!r}' for k, v in st.args.items())})`"
        obs = f"ERROR: {st.error}" if st.error else json.dumps(st.result, ensure_ascii=False)
        lines.append(f"| {st.index} | {_cell(call)} | {_cell(obs)} |")
    lines += ["", f"**Final answer:** {t.final_answer}", ""]
    return "\n".join(lines)


def render_packet(trajs: dict[str, Trajectory]) -> str:
    head = [
        "# Trajectory annotation packet",
        "",
        "Label each trajectory under `guidelines/agent-trajectory-v1.md`. Observations below were produced by "
        "replaying the agent's calls in the environment; they are exactly what the agent saw.",
        "",
        "## Policies",
        "",
    ]
    head += [f"- **{k}**: {v}" for k, v in POLICY_TEXT.items()]
    head.append("")
    return "\n".join(head + [render(t) for t in trajs.values()])


def check(
    labels: list[TrajLabel], trajs: dict[str, Trajectory], hidden: dict[str, dict[str, Any]]
) -> list[TrajFinding]:
    truths = {t.id: truth_for(t, hidden) for t in trajs.values()}
    findings: list[TrajFinding] = []
    seen: set[tuple[str, str]] = set()
    for lb in labels:

        def add(code: str, detail: str = "", lb: TrajLabel = lb) -> None:
            msg = RULES[code][1] + (f": {detail}" if detail else "")
            where = f"{lb.source}:{lb.line}" if lb.source else f"line {lb.line}"
            findings.append(TrajFinding(code, lb.trajectory_id, lb.annotator, msg, where))

        if not lb.annotator.strip():
            add("E409")
        t = trajs.get(lb.trajectory_id)
        if t is None:
            add("E401", repr(lb.trajectory_id))
            continue
        if (lb.trajectory_id, lb.annotator) in seen:
            add("E402")
        seen.add((lb.trajectory_id, lb.annotator))
        n_steps = len(t.calls)
        if lb.outcome not in OUTCOMES:
            add("E403", repr(lb.outcome))
        if lb.final_answer not in FINAL:
            add("E408", repr(lb.final_answer))
        if len(lb.rationale.split()) < MIN_RATIONALE_WORDS:
            add("E406", f"{len(lb.rationale.split())} word(s)")
        fe = lb.first_error_step
        if fe is not None and (not isinstance(fe, int) or isinstance(fe, bool) or not 1 <= fe <= n_steps):
            add("E407", repr(fe))
            fe = None
        claimed: set[tuple[int, str]] = set()
        labelled_unsafe: set[int] = set()
        steps = lb.step_labels if isinstance(lb.step_labels, list) else []
        for sl in steps:
            if not isinstance(sl, dict) or sl.get("label") not in STEP_LABELS:
                add("E404", repr(sl))
                continue
            n = sl.get("step")
            if not isinstance(n, int) or not 1 <= n <= n_steps:
                add("E404", f"step {n!r}")
                continue
            if sl["label"] in ("policy_violation", "unsafe"):
                labelled_unsafe.add(n)
            if sl["label"] == "policy_violation":
                pols = sl.get("policies")
                if not isinstance(pols, list) or not pols or any(p not in POLICY_TEXT for p in pols):
                    add("E405", f"step {n}: {pols!r}")
                    continue
                claimed |= {(n, p) for p in pols}
        if lb.outcome == "success" and labelled_unsafe:
            add("W421")

        truth = truths[t.id]
        if lb.outcome in OUTCOMES and lb.outcome != truth.outcome:
            add("V411", f"labelled {lb.outcome}, replay says {truth.outcome}")
        actual = {(s, p) for s, ps in truth.violations.items() for p in ps}
        for s, p in sorted(actual - claimed):
            add("V412", f"step {s} breaks {p}: {POLICY_TEXT[p]}")
        for s, p in sorted(claimed - actual):
            add("V413", f"step {s} {p}")
        if truth.first_violation is not None and (fe is None or fe > truth.first_violation):
            add("V414", f"labelled {fe}, first violation at step {truth.first_violation}")
        if truth.final_answer and lb.final_answer in FINAL and lb.final_answer != truth.final_answer:
            add("V415", f"labelled {lb.final_answer}, ground truth {truth.final_answer}")
    return findings


def build_traj_report(
    labels: list[TrajLabel], trajs: dict[str, Trajectory], hidden: dict[str, dict[str, Any]], *, gold: str | None = None
) -> str:
    findings = check(labels, trajs, hidden)
    bad = {(f.trajectory_id, f.annotator) for f in findings if f.kind == "error"}
    good = [lb for lb in labels if (lb.trajectory_id, lb.annotator) not in bad and lb.trajectory_id in trajs]
    truths = {t.id: truth_for(t, hidden) for t in trajs.values()}
    annotators = sorted({lb.annotator for lb in good})
    lines = [
        "# Agent-trajectory report",
        "",
        f"- Trajectories: {len(trajs)}; labels read: {len(labels)}; usable: {len(good)}",
        f"- Annotators: {', '.join(annotators) or 'none'}",
        "",
        "## Ground truth from replay",
        "",
        "| Trajectory | Task | Steps | Goal met | Policy violations | Outcome | Final answer |",
        "|---|---|---|---|---|---|---|",
    ]
    for tid, tr in truths.items():
        v = "; ".join(f"step {s}: {', '.join(ps)}" for s, ps in tr.violations.items()) or "-"
        lines.append(
            f"| {tid} | {trajs[tid].task} | {len(trajs[tid].calls)} | {'yes' if tr.replay.success else 'no'} | "
            f"{v} | {tr.outcome} | {tr.final_answer or 'n/a'} |"
        )
    lines += [
        "",
        "## Annotator accuracy",
        "",
        "| Annotator | n | Outcome accuracy | Violation recall | Violation precision | First error exact | "
        "Final-answer accuracy |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in annotators:
        mine = [lb for lb in good if lb.annotator == a]
        out_acc = sum(lb.outcome == truths[lb.trajectory_id].outcome for lb in mine) / len(mine)
        tp = fp = fn = 0
        fe_hits = fe_n = 0
        fa_hits = fa_n = 0
        for lb in mine:
            tr = truths[lb.trajectory_id]
            actual = {(s, p) for s, ps in tr.violations.items() for p in ps}
            claimed = {
                (sl["step"], p)
                for sl in lb.step_labels
                if isinstance(sl, dict) and sl.get("label") == "policy_violation"
                for p in sl.get("policies", [])
            }
            tp, fp, fn = tp + len(actual & claimed), fp + len(claimed - actual), fn + len(actual - claimed)
            if tr.first_violation is not None:
                fe_n += 1
                fe_hits += lb.first_error_step == tr.first_violation
            if tr.final_answer:
                fa_n += 1
                fa_hits += lb.final_answer == tr.final_answer
        lines.append(
            f"| {a} | {len(mine)} | {out_acc:.0%} | {_ratio(tp, tp + fn)} | {_ratio(tp, tp + fp)} | "
            f"{_ratio(fe_hits, fe_n)} | {_ratio(fa_hits, fa_n)} |"
        )
    lines.append("")
    if len(annotators) >= 2:
        lines += [
            "## Agreement",
            "",
            "| Pair | n | Outcome % agree | Outcome kappa | First error agree |",
            "|---|---|---|---|---|",
        ]
        for x, y in combinations(annotators, 2):
            by_x = {lb.trajectory_id: lb for lb in good if lb.annotator == x}
            by_y = {lb.trajectory_id: lb for lb in good if lb.annotator == y}
            ids = sorted(set(by_x) & set(by_y))
            if not ids:
                continue
            ox, oy = [by_x[i].outcome for i in ids], [by_y[i].outcome for i in ids]
            k = cohen_kappa(ox, oy, categories=OUTCOMES)
            fe = sum(by_x[i].first_error_step == by_y[i].first_error_step for i in ids) / len(ids)
            lines.append(
                f"| {x} / {y} | {len(ids)} | {percent_agreement(ox, oy):.0%} | "
                f"{'undefined' if math.isnan(k) else f'{k:.3f}'} ({interpret_kappa(k)}) | {fe:.0%} |"
            )
        lines.append("")
    lines += ["## Findings", ""]
    if findings:
        lines += ["| Where | Code | Kind | Annotator | Trajectory | Message |", "|---|---|---|---|---|---|"]
        order = {"error": 0, "mismatch": 1, "warning": 2}
        for f in sorted(findings, key=lambda f: (order[f.kind], f.trajectory_id, f.annotator)):
            lines.append(
                f"| {f.where} | {f.code} | {f.kind} | {f.annotator} | {f.trajectory_id} | {_cell(f.message)} |"
            )
    else:
        lines.append("No findings.")
    lines += [
        "",
        "## How to read this",
        "",
        "- Outcome and policy violations are computed by replaying the agent's calls; they are not opinions.",
        "- 'Violation recall' is the safety-critical number: a missed violation is harmful behaviour that would be "
        "rewarded in training data.",
        "- First error = earliest policy violation here; steps that are merely unnecessary are not errors.",
        "",
    ]
    return "\n".join(lines)


def _ratio(num: int, den: int) -> str:
    return "n/a" if den == 0 else f"{num}/{den}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
