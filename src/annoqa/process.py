"""Process-reward annotation: step labels and first-error location for worked solutions.

Follows the first-error convention used for process reward models (PRM800K-style): label each
step ``good`` (+1), ``neutral`` (0) or ``bad`` (-1) up to and including the first bad step, and
stop there, because later steps inherit the error.

Checked mechanically:
- every arithmetic step (``calc`` / ``claims``) is re-evaluated exactly with fractions;
- the final answer is compared with the known answer;
- labels are compared with hidden ground truth for errors arithmetic cannot reveal
  (a wrong setup or an invalid inference computed correctly).
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from annoqa.agreement import krippendorff_alpha
from annoqa.schema import LoadError, read_jsonl

STEP_LABELS = ("good", "neutral", "bad")
ERROR_TYPES = ("arithmetic", "misread", "setup", "logic")
MIN_RATIONALE_WORDS = 15

Kind = Literal["error", "mismatch", "warning"]
RULES: dict[str, tuple[Kind, str]] = {
    "E601": ("error", "solution_id does not match any solution"),
    "E602": ("error", "same annotator labelled the same solution twice"),
    "E603": ("error", "step_labels must be a list of good/neutral/bad no longer than the solution"),
    "E604": ("error", "first_error_step must equal the position of the first 'bad' label (or be null if none)"),
    "E605": ("error", "error_type must be arithmetic/misread/setup/logic when there is a first error, null otherwise"),
    "E606": ("error", f"rationale is shorter than {MIN_RATIONALE_WORDS} words"),
    "E607": ("error", "final_answer_correct must be true or false"),
    "E608": ("error", "annotator id is empty"),
    "V611": ("mismatch", "a step labelled good/neutral has arithmetic that does not check out"),
    "V612": ("mismatch", "error_type 'arithmetic', but the arithmetic at that step is correct"),
    "V613": ("mismatch", "final_answer_correct differs from the known answer"),
    "V614": ("mismatch", "first error differs from ground truth"),
    "V615": ("mismatch", "error type differs from ground truth"),
    "V616": ("mismatch", "the final answer is wrong, so the solution must contain an error, but none is labelled"),
    "W621": (
        "warning",
        "steps after the first error are labelled; the first-error convention stops at the first bad step",
    ),
    "W622": ("warning", "no labels for steps before the first error; every step up to it must be labelled"),
}


class CalcError(ValueError):
    pass


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def evaluate(expr: str) -> Fraction:
    """Exact arithmetic on + - * / and parentheses. Decimals are read exactly (3.50 -> 7/2)."""

    def walk(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
            return Fraction(Decimal(repr(node.value)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            right = walk(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise CalcError("division by zero")
            return _OPS[type(node.op)](walk(node.left), right)  # type: ignore[no-any-return]
        raise CalcError(f"unsupported expression: {ast.dump(node)[:60]}")

    try:
        return walk(ast.parse(expr, mode="eval"))
    except SyntaxError as exc:
        raise CalcError(f"cannot parse {expr!r}") from exc


def as_number(text: str) -> Fraction | None:
    try:
        return Fraction(Decimal(text.replace(",", "").replace("$", "").strip()))
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class Solution:
    id: str
    problem: str
    answer: str
    steps: tuple[dict[str, Any], ...]
    final_answer: str

    def arithmetic_ok(self, i: int) -> bool | None:
        """True/False for a step with calc/claims, None if the step has no arithmetic to check."""
        st = self.steps[i - 1]
        if "calc" not in st:
            return None
        claimed = as_number(str(st["claims"]))
        try:
            return claimed is not None and evaluate(str(st["calc"])) == claimed
        except CalcError:
            return False

    @property
    def first_arithmetic_error(self) -> int | None:
        return next((i for i in range(1, len(self.steps) + 1) if self.arithmetic_ok(i) is False), None)

    @property
    def final_correct(self) -> bool:
        a, b = as_number(self.final_answer), as_number(self.answer)
        return (a == b) if a is not None and b is not None else self.final_answer == self.answer


@dataclass
class StepLabel:
    solution_id: str
    annotator: str
    step_labels: Any
    first_error_step: Any
    error_type: Any
    final_answer_correct: Any
    rationale: str
    line: int = 0
    source: str = ""


@dataclass(frozen=True)
class StepFinding:
    code: str
    solution_id: str
    annotator: str
    message: str
    where: str

    @property
    def kind(self) -> Kind:
        return RULES[self.code][0]


def load_solutions(path: Path) -> dict[str, Solution]:
    out: dict[str, Solution] = {}
    for n, o in read_jsonl(path):
        try:
            out[str(o["id"])] = Solution(
                str(o["id"]), str(o["problem"]), str(o["answer"]), tuple(o["steps"]), str(o["final_answer"])
            )
        except KeyError as exc:
            raise LoadError(f"{path}:{n}: solution is missing {exc.args[0]!r}") from exc
    return out


def load_step_hidden(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    return {str(o["id"]): o for _n, o in read_jsonl(path)}


def load_step_labels(path: Path) -> list[StepLabel]:
    return [
        StepLabel(
            str(o.get("solution_id", "")),
            str(o.get("annotator", "")),
            o.get("step_labels"),
            o.get("first_error_step"),
            o.get("error_type"),
            o.get("final_answer_correct"),
            str(o.get("rationale", "")),
            n,
            str(path),
        )
        for n, o in read_jsonl(path)
    ]


def check(labels: list[StepLabel], sols: dict[str, Solution], hidden: dict[str, dict[str, Any]]) -> list[StepFinding]:
    findings: list[StepFinding] = []
    seen: set[tuple[str, str]] = set()
    for lb in labels:

        def add(code: str, detail: str = "", lb: StepLabel = lb) -> None:
            msg = RULES[code][1] + (f": {detail}" if detail else "")
            where = f"{lb.source}:{lb.line}" if lb.source else f"line {lb.line}"
            findings.append(StepFinding(code, lb.solution_id, lb.annotator, msg, where))

        if not lb.annotator.strip():
            add("E608")
        sol = sols.get(lb.solution_id)
        if sol is None:
            add("E601", repr(lb.solution_id))
            continue
        if (lb.solution_id, lb.annotator) in seen:
            add("E602")
        seen.add((lb.solution_id, lb.annotator))
        if len(lb.rationale.split()) < MIN_RATIONALE_WORDS:
            add("E606", f"{len(lb.rationale.split())} word(s)")
        if not isinstance(lb.final_answer_correct, bool):
            add("E607")
        labels_ok = (
            isinstance(lb.step_labels, list)
            and len(lb.step_labels) <= len(sol.steps)
            and all(x in STEP_LABELS for x in lb.step_labels)
        )
        if not labels_ok:
            add("E603")
            continue
        steps: list[str] = lb.step_labels
        first_bad = next((i for i, x in enumerate(steps, start=1) if x == "bad"), None)
        if lb.first_error_step != first_bad:
            add("E604", f"first_error_step={lb.first_error_step!r}, first 'bad' label at {first_bad!r}")
        if (first_bad is None) != (lb.error_type is None) or (
            lb.error_type is not None and lb.error_type not in ERROR_TYPES
        ):
            add("E605", repr(lb.error_type))
        if first_bad is not None and len(steps) > first_bad:
            add("W621", f"{len(steps) - first_bad} step(s) after step {first_bad}")
        if first_bad is None and len(steps) < len(sol.steps):
            add("W622", f"{len(steps)} of {len(sol.steps)} steps labelled")

        # mechanical checks
        for i, x in enumerate(steps, start=1):
            if x in ("good", "neutral") and sol.arithmetic_ok(i) is False:
                st = sol.steps[i - 1]
                add("V611", f"step {i}: {st['calc']} = {_fmt_frac(evaluate(st['calc']))}, not {st['claims']}")
        if lb.error_type == "arithmetic" and first_bad is not None and sol.arithmetic_ok(first_bad) is True:
            add("V612", f"step {first_bad}")
        if isinstance(lb.final_answer_correct, bool) and lb.final_answer_correct != sol.final_correct:
            add("V613", f"solution ends on {sol.final_answer!r}, known answer {sol.answer!r}")
        if not sol.final_correct and first_bad is None:
            add("V616")
        h = hidden.get(sol.id)
        if h is not None:
            if first_bad != h["first_error_step"]:
                add("V614", f"labelled {first_bad}, ground truth {h['first_error_step']}")
            elif first_bad is not None and lb.error_type != h["error_type"]:
                add("V615", f"labelled {lb.error_type}, ground truth {h['error_type']}")
    return findings


def build_step_report(labels: list[StepLabel], sols: dict[str, Solution], hidden: dict[str, dict[str, Any]]) -> str:
    findings = check(labels, sols, hidden)
    bad = {(f.solution_id, f.annotator) for f in findings if f.kind == "error"}
    good = [lb for lb in labels if (lb.solution_id, lb.annotator) not in bad and lb.solution_id in sols]
    annotators = sorted({lb.annotator for lb in good})
    lines = [
        "# Process-reward report",
        "",
        f"- Solutions: {len(sols)}; labels read: {len(labels)}; usable: {len(good)}",
        f"- Annotators: {', '.join(annotators) or 'none'}",
        "",
        "## Ground truth",
        "",
        "| Solution | Final answer | Known | Final correct | First arithmetic error (computed) | First error (truth) | Type | Outcome vs process |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sid, sol in sols.items():
        h = hidden.get(sid, {})
        fe = h.get("first_error_step")
        note = "**lucky: right answer, wrong process**" if sol.final_correct and fe is not None else ""
        lines.append(
            f"| {sid} | {sol.final_answer} | {sol.answer} | {'yes' if sol.final_correct else 'no'} | "
            f"{sol.first_arithmetic_error or '-'} | {fe or '-'} | {h.get('error_type') or '-'} | {note} |"
        )
    lines += [
        "",
        "## Annotator accuracy",
        "",
        "| Annotator | n | First error exact | Error type (when step right) | Final-answer accuracy | Arithmetic errors missed |",
        "|---|---|---|---|---|---|",
    ]
    for a in annotators:
        mine = [lb for lb in good if lb.annotator == a]
        fe_hits = sum(
            lb.first_error_step == hidden.get(lb.solution_id, {}).get("first_error_step")
            for lb in mine
            if lb.solution_id in hidden
        )
        n_h = sum(lb.solution_id in hidden for lb in mine)
        typed = [
            lb
            for lb in mine
            if lb.solution_id in hidden
            and lb.first_error_step == hidden[lb.solution_id]["first_error_step"]
            and lb.first_error_step is not None
        ]
        type_hits = sum(lb.error_type == hidden[lb.solution_id]["error_type"] for lb in typed)
        fa = sum(lb.final_answer_correct == sols[lb.solution_id].final_correct for lb in mine)
        missed = sum(1 for f in findings if f.annotator == a and f.code == "V611")
        lines.append(
            f"| {a} | {len(mine)} | {fe_hits}/{n_h} | {type_hits}/{len(typed)} | {fa}/{len(mine)} | {missed} |"
        )
    lines.append("")
    if len(annotators) >= 2:
        lines += [
            "## Agreement",
            "",
            "| Pair | Same first error | Step-label alpha (nominal, labelled steps) |",
            "|---|---|---|",
        ]
        for x, y in combinations(annotators, 2):
            bx = {lb.solution_id: lb for lb in good if lb.annotator == x}
            by = {lb.solution_id: lb for lb in good if lb.annotator == y}
            ids = sorted(set(bx) & set(by))
            if not ids:
                continue
            same = sum(bx[i].first_error_step == by[i].first_error_step for i in ids)
            units = [
                {
                    x: (bx[i].step_labels[k] if k < len(bx[i].step_labels) else None),
                    y: (by[i].step_labels[k] if k < len(by[i].step_labels) else None),
                }
                for i in ids
                for k in range(len(sols[i].steps))
            ]
            alpha = krippendorff_alpha(units)
            lines.append(f"| {x} / {y} | {same}/{len(ids)} | {alpha:.3f} |")
        lines.append("")
    lines += ["## Findings", ""]
    if findings:
        lines += ["| Where | Code | Kind | Annotator | Solution | Message |", "|---|---|---|---|---|---|"]
        order = {"error": 0, "mismatch": 1, "warning": 2}
        for f in sorted(findings, key=lambda f: (order[f.kind], f.solution_id, f.annotator)):
            lines.append(
                f"| {f.where} | {f.code} | {f.kind} | {f.annotator} | {f.solution_id} | {f.message.replace('|', '/')} |"
            )
    else:
        lines.append("No findings.")
    lines += [
        "",
        "## How to read this",
        "",
        "- An **outcome** reward only checks the final answer; a **process** reward checks every step. A "
        "'lucky' solution (right answer, wrong steps) gets full outcome reward, and a rater who labels it correct "
        "teaches a model that broken reasoning is fine.",
        "- Arithmetic is re-checked exactly (fractions, no floating point). Setup, misread and logic errors "
        "compute correctly, so only a careful human finds them; they are scored against hidden ground truth.",
        "",
    ]
    return "\n".join(lines)


def render_solutions(sols: dict[str, Solution]) -> str:
    out = [
        "# Process-reward annotation packet",
        "",
        "Label each step good / neutral / bad up to the first bad step "
        "(see `guidelines/process-reward-v1.md`). Do not look at `data/process/hidden.jsonl`.",
        "",
    ]
    for sol in sols.values():
        out += [f"## {sol.id}", "", f"**Problem.** {sol.problem}", ""]
        out += [
            f"{i}. {st['text']}" + (f" `{st['calc']} = {st['claims']}`" if "calc" in st else "")
            for i, st in enumerate(sol.steps, start=1)
        ]
        out.append("")
    return "\n".join(out)


def _fmt_frac(f: Fraction) -> str:
    return str(f.numerator) if f.denominator == 1 else f"{float(f):g}"
