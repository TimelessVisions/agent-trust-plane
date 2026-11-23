"""Rubric authoring for rubric-based rewards: lint, score, and measure whether a rubric works.

A rubric is a list of weighted criteria for one prompt. Positive weights reward a property;
negative weights (penalties) subtract when a known failure mode is present. Criteria of kind
``verifiable`` carry a machine ``check``; ``judgment`` criteria are graded by people.

A rubric is good if it is:
- **well-formed**: atomic, specific, weighted, with penalties (``lint``);
- **reliable**: different graders mark each criterion the same way (per-criterion agreement);
- **valid**: its scores rank responses in their known quality order (Kendall's tau);
- **hack-resistant**: a long, keyword-stuffed, wrong response does not score well (hack gap).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from annoqa.agreement import cohen_kappa, interpret_kappa
from annoqa.schema import LoadError, read_jsonl

VAGUE = (
    "good",
    "well",
    "appropriate",
    "appropriately",
    "clear",
    "clearly",
    "comprehensive",
    "professional",
    "empathetic",
    "efficient",
    "pythonic",
    "quality",
    "nice",
    "proper",
    "properly",
    "adequate",
    "adequately",
    "relevant",
    "helpful",
    "detailed",
    "thorough",
    "reasonable",
    "best",
)
LENGTH_WORDS = ("length", "short", "long", "brief", "concise", "lengthy")
NUMBER = r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty|hundred)\b"
STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "is",
        "are",
        "be",
        "it",
        "its",
        "for",
        "in",
        "on",
        "with",
        "by",
        "as",
        "or",
        "and",
        "that",
        "this",
        "from",
        "at",
    ]
)

Kind = Literal["error", "warning"]
LINT_RULES: dict[str, tuple[Kind, str]] = {
    "L500": ("error", "criterion is malformed (needs id, text, a non-zero integer weight, kind judgment|verifiable)"),
    "L501": ("warning", "vague term: graders will read it differently"),
    "L502": ("warning", "compound criterion: split it so each criterion checks one thing"),
    "L503": ("warning", "all weights are equal: the rubric does not say what matters most"),
    "L504": ("warning", "no penalty criterion: known failure modes cost nothing"),
    "L505": ("warning", "length requirement without a number"),
    "L506": ("error", "verifiable criterion without a valid check"),
    "L507": ("warning", "two criteria overlap heavily (double counting)"),
    "L508": ("warning", "fewer than 4 criteria: too coarse to separate responses"),
    "L509": ("warning", "penalty text should name the failure mode (start with 'PENALTY:')"),
}


@dataclass(frozen=True)
class Criterion:
    id: str
    text: str
    weight: int
    kind: str
    check: dict[str, Any] | None


@dataclass(frozen=True)
class Rubric:
    task_id: str
    version: str
    criteria: tuple[Criterion, ...]


@dataclass(frozen=True)
class Response:
    id: str
    tier: int
    text: str


@dataclass(frozen=True)
class RubricTask:
    id: str
    prompt: str
    responses: tuple[Response, ...]


@dataclass(frozen=True)
class LintFinding:
    code: str
    task_id: str
    version: str
    criterion: str
    message: str

    @property
    def kind(self) -> Kind:
        return LINT_RULES[self.code][0]


def load_rubric_tasks(path: Path) -> dict[str, RubricTask]:
    out: dict[str, RubricTask] = {}
    for n, o in read_jsonl(path):
        try:
            resp = tuple(Response(str(r["id"]), int(r["tier"]), str(r["text"])) for r in o["responses"])
            out[str(o["id"])] = RubricTask(str(o["id"]), str(o["prompt"]), resp)
        except (KeyError, TypeError, ValueError) as exc:
            raise LoadError(f"{path}:{n}: malformed rubric task ({exc})") from exc
    return out


def load_rubrics(path: Path) -> list[Rubric]:
    out: list[Rubric] = []
    for _n, o in read_jsonl(path):
        crits = tuple(
            Criterion(
                str(c.get("id", "")),
                str(c.get("text", "")),
                _int_weight(c.get("weight")),
                str(c.get("kind", "")),
                c.get("check") if isinstance(c.get("check"), dict) else None,
            )
            for c in o.get("criteria", [])
            if isinstance(c, dict)
        )
        out.append(Rubric(str(o.get("task_id", "")), str(o.get("version", "")), crits))
    return out


def _int_weight(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def load_grades(path: Path) -> list[dict[str, Any]]:
    return [o for _n, o in read_jsonl(path)]


# ------------------------------------------------------------------ lint


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _valid_check(check: dict[str, Any] | None) -> bool:
    if not check or len(check) != 1:
        return False
    ((key, val),) = check.items()
    if key == "includes_any":
        return isinstance(val, list) and bool(val) and all(isinstance(v, str) and v for v in val)
    if key == "max_words":
        return isinstance(val, int) and not isinstance(val, bool) and val > 0
    if key == "regex":
        try:
            re.compile(str(val))
        except re.error:
            return False
        return True
    return False


def lint(rubric: Rubric) -> list[LintFinding]:
    out: list[LintFinding] = []

    def add(code: str, crit: str = "-", detail: str = "") -> None:
        msg = LINT_RULES[code][1] + (f": {detail}" if detail else "")
        out.append(LintFinding(code, rubric.task_id, rubric.version, crit, msg))

    for c in rubric.criteria:
        if not c.id or not c.text.strip() or c.weight == 0 or c.kind not in ("judgment", "verifiable"):
            add("L500", c.id or "?")
            continue
        words = _words(c.text)
        vague = sorted({w for w in words if w in VAGUE})
        if vague:
            add("L501", c.id, ", ".join(vague))
        body = re.sub(r"\(.*?\)", "", c.text.lower())
        if re.search(r"\band\b|\betc\b|and/or", body):
            add("L502", c.id, repr(c.text))
        if any(w in LENGTH_WORDS for w in words) and not re.search(NUMBER, c.text.lower()):
            add("L505", c.id)
        if c.kind == "verifiable" and not _valid_check(c.check):
            add("L506", c.id)
        if c.weight < 0 and not c.text.startswith("PENALTY:"):
            add("L509", c.id)
    if len({c.weight for c in rubric.criteria if c.weight > 0}) <= 1 and len(rubric.criteria) > 2:
        add("L503")
    if not any(c.weight < 0 for c in rubric.criteria):
        add("L504")
    if len(rubric.criteria) < 4:
        add("L508")
    for a, b in combinations(rubric.criteria, 2):
        wa = {w for w in _words(a.text) if w not in STOP and w != "penalty"}
        wb = {w for w in _words(b.text) if w not in STOP and w != "penalty"}
        if wa and wb and len(wa & wb) / len(wa | wb) >= 0.5:
            add("L507", f"{a.id}/{b.id}")
    return out


# ------------------------------------------------------------------ scoring


def auto_check(check: dict[str, Any], text: str) -> bool:
    ((key, val),) = check.items()
    low = text.lower()
    if key == "includes_any":
        return any(v.lower() in low for v in val)
    if key == "max_words":
        return len(text.split()) <= int(val)
    return re.search(str(val), text) is not None


def marks_for(rubric: Rubric, response: Response, judged: dict[str, bool]) -> dict[str, bool | None]:
    """Criterion -> met. Verifiable criteria are computed; judgment criteria come from a grader (None if ungraded)."""
    out: dict[str, bool | None] = {}
    for c in rubric.criteria:
        if c.kind == "verifiable" and _valid_check(c.check):
            out[c.id] = auto_check(c.check, response.text)  # type: ignore[arg-type]
        else:
            out[c.id] = judged.get(c.id)
    return out


def score(rubric: Rubric, marks: dict[str, bool | None]) -> float:
    """Weighted score normalised by the maximum positive total, so 1.0 = every reward criterion met, no penalties."""
    max_pos = sum(c.weight for c in rubric.criteria if c.weight > 0)
    raw = sum(c.weight for c in rubric.criteria if marks.get(c.id))
    return raw / max_pos if max_pos else math.nan


def kendall_tau(xs: list[float], ys: list[float]) -> float:
    """Tau-b, handling ties."""
    conc = disc = tx = ty = 0
    for i, j in combinations(range(len(xs)), 2):
        dx, dy = xs[i] - xs[j], ys[i] - ys[j]
        if dx == 0 and dy == 0:
            continue
        if dx == 0:
            tx += 1
        elif dy == 0:
            ty += 1
        elif (dx > 0) == (dy > 0):
            conc += 1
        else:
            disc += 1
    denom = math.sqrt((conc + disc + tx) * (conc + disc + ty))
    return (conc - disc) / denom if denom else math.nan


@dataclass(frozen=True)
class RubricResult:
    task_id: str
    version: str
    scores: dict[str, float]  # response id -> score (reference grader)
    tau: float
    hack_gap: float  # best-tier score minus hack (worst-tier) score; <= 0 means the hack wins
    non_discriminating: tuple[str, ...]


def evaluate(rubric: Rubric, task: RubricTask, judged_by_response: dict[str, dict[str, bool]]) -> RubricResult:
    scores = {r.id: score(rubric, marks_for(rubric, r, judged_by_response.get(r.id, {}))) for r in task.responses}
    order = [r for r in task.responses]
    tau = kendall_tau([scores[r.id] for r in order], [-float(r.tier) for r in order])
    best = min(task.responses, key=lambda r: r.tier)
    worst = max(task.responses, key=lambda r: r.tier)
    flat = []
    for c in rubric.criteria:
        vals = {marks_for(rubric, r, judged_by_response.get(r.id, {}))[c.id] for r in task.responses}
        if len(vals) == 1:
            flat.append(c.id)
    return RubricResult(task.id, rubric.version, scores, tau, scores[best.id] - scores[worst.id], tuple(flat))


def grader_index(grades: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, dict[str, bool]]]:
    """(grader, task, version) -> response -> marks."""
    out: dict[tuple[str, str, str], dict[str, dict[str, bool]]] = {}
    for g in grades:
        key = (str(g["grader"]), str(g["task_id"]), str(g["version"]))
        out.setdefault(key, {})[str(g["response_id"])] = {k: bool(v) for k, v in g["marks"].items()}
    return out


def build_rubric_report(
    tasks: dict[str, RubricTask], rubrics: list[Rubric], grades: list[dict[str, Any]], *, reference: str = "ref"
) -> str:
    idx = grader_index(grades)
    graders = sorted({k[0] for k in idx})
    lines = [
        "# Rubric report",
        "",
        f"- Tasks: {len(tasks)}; rubrics: {len(rubrics)}; graders: {', '.join(graders)}",
        "",
    ]
    lines += [
        "## Summary by rubric",
        "",
        "| Task | Version | Lint warnings | Lint errors | Kendall tau vs known ranking | Hack gap | Hack wins? "
        "| Non-discriminating criteria | Grader agreement (kappa) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    details: list[str] = []
    for rb in sorted(rubrics, key=lambda r: (r.task_id, r.version)):
        task = tasks.get(rb.task_id)
        if task is None:
            continue
        findings = lint(rb)
        res = evaluate(rb, task, idx.get((reference, rb.task_id, rb.version), {}))
        agree = _agreement(rb, task, idx, graders)
        lines.append(
            f"| {rb.task_id} | {rb.version} | {sum(f.kind == 'warning' for f in findings)} | "
            f"{sum(f.kind == 'error' for f in findings)} | {_fmt(res.tau)} | {res.hack_gap:+.2f} | "
            f"{'**yes**' if res.hack_gap <= 0 else 'no'} | {', '.join(res.non_discriminating) or '-'} | {agree} |"
        )
        details += [f"### {rb.task_id} {rb.version}", "", "| Response | Tier | Score |", "|---|---|---|"]
        for r in task.responses:
            hack = " (hack)" if r.tier == max(x.tier for x in task.responses) else ""
            details.append(f"| {r.id} | {r.tier}{hack} | {res.scores[r.id]:+.2f} |")
        details.append("")
        if findings:
            details += [f"- `{f.code}` {f.criterion}: {f.message}" for f in findings]
            details.append("")
    lines += ["", "## Details", "", *details]
    lines += [
        "## How to read this",
        "",
        "- **Kendall tau** compares rubric scores with the known quality order of the responses: 1.0 = perfect "
        "order, 0 = no relation, negative = the rubric prefers worse answers.",
        "- **Hack gap** = score of the best response minus score of the reward-hacking response (long, "
        "keyword-stuffed, confidently wrong). At or below zero, an RL policy trained on this rubric is paid to hack.",
        "- **Non-discriminating** criteria are met by every response or by none: they add no training signal.",
        "- **Grader agreement** is Cohen's kappa over all judgment marks of two graders; low agreement on a "
        "criterion usually means its wording is vague (see lint L501/L502).",
        "",
    ]
    return "\n".join(lines)


def _agreement(
    rb: Rubric, task: RubricTask, idx: dict[tuple[str, str, str], dict[str, dict[str, bool]]], graders: list[str]
) -> str:
    cells = []
    judgment = [c.id for c in rb.criteria if c.kind == "judgment"]
    for x, y in combinations(graders, 2):
        gx, gy = idx.get((x, rb.task_id, rb.version)), idx.get((y, rb.task_id, rb.version))
        if not gx or not gy:
            continue
        a = [
            gx[r.id][c]
            for r in task.responses
            for c in judgment
            if r.id in gx and r.id in gy and c in gx[r.id] and c in gy[r.id]
        ]
        b = [
            gy[r.id][c]
            for r in task.responses
            for c in judgment
            if r.id in gx and r.id in gy and c in gx[r.id] and c in gy[r.id]
        ]
        k = cohen_kappa(a, b, categories=(False, True))
        cells.append(f"{_fmt(k)} ({interpret_kappa(k)})")
    return "; ".join(cells) or "-"


def _fmt(v: float) -> str:
    return "undefined" if math.isnan(v) else f"{v:.2f}"
