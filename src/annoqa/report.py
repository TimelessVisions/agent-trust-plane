"""Agreement and adjudication report across annotators, as Markdown."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from annoqa.agreement import cohen_kappa, interpret_alpha, interpret_kappa, krippendorff_alpha, percent_agreement
from annoqa.schema import DIMENSIONS, FLAGS, PREFERENCES, SCALE, SIDES, Item, Label
from annoqa.validate import Finding, validate


@dataclass(frozen=True)
class Disagreement:
    item_id: str
    severity: int
    reasons: tuple[str, ...]


def usable(labels: list[Label], findings: list[Finding]) -> list[Label]:
    """Labels with no validation errors; warnings are kept."""
    broken = {(f.item_id, f.annotator) for f in findings if f.severity == "error"}
    return [lb for lb in labels if (lb.item_id, lb.annotator) not in broken]


def index(labels: list[Label]) -> dict[str, dict[str, Label]]:
    by_item: dict[str, dict[str, Label]] = defaultdict(dict)
    for lb in labels:
        by_item[lb.item_id][lb.annotator] = lb
    return by_item


def find_disagreements(by_item: dict[str, dict[str, Label]]) -> list[Disagreement]:
    out: list[Disagreement] = []
    for item_id, per in by_item.items():
        if len(per) < 2:
            continue
        reasons: list[str] = []
        severity = 0
        prefs = {lb.preference for lb in per.values()}
        if len(prefs) > 1:
            opposite = {"A", "B"} <= prefs
            severity += 3 if opposite else 2
            reasons.append("opposite preferences (A vs B)" if opposite else f"preferences differ: {sorted(prefs)}")
        for side in SIDES:
            for dim in DIMENSIONS:
                vals = [lb.scores[side][dim] for lb in per.values()]
                spread = max(vals) - min(vals)
                if spread >= 2:
                    severity += spread - 1
                    reasons.append(f"{side}.{dim} spread {spread} ({min(vals)}-{max(vals)})")
            flag_sets = [frozenset(lb.flags.get(side, [])) for lb in per.values()]
            if len(set(flag_sets)) > 1:
                union = frozenset().union(*flag_sets)
                common = frozenset.intersection(*flag_sets)
                severity += 1
                reasons.append(f"{side} flags differ: {sorted(union - common)}")
        if reasons:
            out.append(Disagreement(item_id, severity, tuple(reasons)))
    return sorted(out, key=lambda d: (-d.severity, d.item_id))


def build_report(
    labels: list[Label],
    items: dict[str, Item],
    *,
    gold: str | None = None,
    max_disagreements: int = 25,
) -> str:
    findings = validate(labels, items)
    good = usable(labels, findings)
    by_item = index(good)
    annotators = sorted({lb.annotator for lb in good})
    lines: list[str] = ["# Annotation agreement report", ""]

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    lines += [
        f"- Items in the set: {len(items)}",
        f"- Annotators: {', '.join(annotators) or 'none'}",
        f"- Labels read: {len(labels)}; usable: {len(good)} "
        f"({len(errors)} error(s) excluded labels, {len(warnings)} warning(s) kept)",
        f"- Items rated by 2+ annotators: {sum(1 for per in by_item.values() if len(per) >= 2)}",
        "",
    ]
    if findings:
        lines += [
            "## Validation findings",
            "",
            "| Where | Code | Annotator | Item | Message |",
            "|---|---|---|---|---|",
        ]
        for f in findings:
            lines.append(f"| {f.where} | {f.code} | {f.annotator} | {f.item_id} | {_cell(f.message)} |")
        lines.append("")

    lines += _agreement_section(by_item, annotators)
    if gold:
        lines += _gold_section(by_item, annotators, gold)
    lines += _disagreement_section(by_item, items, max_disagreements)
    lines += [
        "## How to read this",
        "",
        "- Kappa and alpha correct for chance agreement: 0 is chance level, 1 is perfect, "
        "negative is worse than chance. Alpha readings follow Krippendorff (2004): >= 0.800 reliable, "
        "0.667-0.800 tentative. Kappa readings follow Landis & Koch (1977). Both are guides, not proofs.",
        "- Scores are compared as ordinal (alpha) and with quadratic weights (kappa), "
        "so a 4-vs-5 split costs far less than a 1-vs-5 split.",
        "- 'undefined' means every rating fell in one category, so chance agreement is total "
        "and the statistic cannot be computed. It is not a perfect score.",
        "- Small samples give unstable estimates; treat numbers on fewer than ~30 items with caution.",
        "",
    ]
    return "\n".join(lines)


def _agreement_section(by_item: dict[str, dict[str, Label]], annotators: list[str]) -> list[str]:
    lines = ["## Agreement", ""]
    if len(annotators) < 2:
        return lines + ["Fewer than two annotators: agreement is not computed.", ""]
    shared_units = [per for per in by_item.values() if len(per) >= 2]

    rows: list[tuple[str, float, str]] = []
    rows.append(
        (
            "preference (A/B/tie)",
            krippendorff_alpha({a: lb.preference for a, lb in per.items()} for per in shared_units),
            "nominal",
        )
    )
    for dim in DIMENSIONS:
        units = [{a: lb.scores[side][dim] for a, lb in per.items()} for per in shared_units for side in SIDES]
        rows.append((f"score: {dim}", krippendorff_alpha(units, level="ordinal"), "ordinal"))
    for flag in FLAGS:
        units = [{a: flag in lb.flags.get(side, []) for a, lb in per.items()} for per in shared_units for side in SIDES]
        if any(v for u in units for v in u.values()):
            rows.append((f"flag: {flag}", krippendorff_alpha(units), "nominal"))

    lines += [
        "Krippendorff's alpha over all annotators:",
        "",
        "| Field | Alpha | Level | Reading |",
        "|---|---|---|---|",
    ]
    for name, value, level in rows:
        lines.append(f"| {name} | {_fmt(value)} | {level} | {interpret_alpha(value)} |")
    lines.append("")

    lines += [
        "Pairwise (items both annotators rated):",
        "",
        "| Pair | n | Preference % agree | Preference kappa | Mean quadratic-weighted kappa, scores |",
        "|---|---|---|---|---|",
    ]
    for a, b in combinations(annotators, 2):
        both = [per for per in by_item.values() if a in per and b in per]
        if not both:
            lines.append(f"| {a} / {b} | 0 | - | - | - |")
            continue
        pa = [per[a].preference for per in both]
        pb = [per[b].preference for per in both]
        kappas = [
            cohen_kappa(
                [per[a].scores[s][d] for per in both],
                [per[b].scores[s][d] for per in both],
                weights="quadratic",
                categories=SCALE,
            )
            for s in SIDES
            for d in DIMENSIONS
        ]
        defined = [k for k in kappas if not math.isnan(k)]
        mean_k = sum(defined) / len(defined) if defined else math.nan
        pref_k = cohen_kappa(pa, pb, categories=PREFERENCES)
        lines.append(
            f"| {a} / {b} | {len(both)} | {percent_agreement(pa, pb):.0%} | "
            f"{_fmt(pref_k)} ({interpret_kappa(pref_k)}) | {_fmt(mean_k)} |"
        )
    lines.append("")
    return lines


def _gold_section(by_item: dict[str, dict[str, Label]], annotators: list[str], gold: str) -> list[str]:
    lines = [f"## Accuracy against gold (`{gold}`)", ""]
    if gold not in annotators:
        return lines + [f"No usable labels from `{gold}`.", ""]
    lines += [
        "| Annotator | n | Preference accuracy | Mean absolute score error | Flag recall | Flag precision |",
        "|---|---|---|---|---|---|",
    ]
    for ann in annotators:
        if ann == gold:
            continue
        both = [per for per in by_item.values() if gold in per and ann in per]
        if not both:
            continue
        acc = sum(per[ann].preference == per[gold].preference for per in both) / len(both)
        errs = [abs(per[ann].scores[s][d] - per[gold].scores[s][d]) for per in both for s in SIDES for d in DIMENSIONS]
        tp = fp = fn = 0
        for per in both:
            for s in SIDES:
                mine, ref = set(per[ann].flags.get(s, [])), set(per[gold].flags.get(s, []))
                tp += len(mine & ref)
                fp += len(mine - ref)
                fn += len(ref - mine)
        recall = tp / (tp + fn) if tp + fn else math.nan
        precision = tp / (tp + fp) if tp + fp else math.nan
        lines.append(
            f"| {ann} | {len(both)} | {acc:.0%} | {sum(errs) / len(errs):.2f} | {_pct(recall)} | {_pct(precision)} |"
        )
    lines.append("")
    return lines


def _disagreement_section(by_item: dict[str, dict[str, Label]], items: dict[str, Item], limit: int) -> list[str]:
    found = find_disagreements(by_item)
    lines = ["## Adjudication queue", ""]
    if not found:
        return lines + ["No disagreements on items rated by two or more annotators.", ""]
    lines.append(f"{len(found)} item(s) need adjudication, most severe first (showing up to {limit}).")
    lines.append("")
    for d in found[:limit]:
        item = items.get(d.item_id)
        lines.append(f"### {d.item_id} (severity {d.severity})")
        lines.append("")
        if item:
            lines.append(f"> {_snippet(item.prompt)}")
            lines.append("")
        lines += [f"- {r}" for r in d.reasons]
        lines += [
            "",
            "| Annotator | Pref | Total A | Total B | Flags A | Flags B | Rationale |",
            "|---|---|---|---|---|---|---|",
        ]
        for ann, lb in sorted(by_item[d.item_id].items()):
            lines.append(
                f"| {ann} | {lb.preference} | {lb.total('A')} | {lb.total('B')} | "
                f"{', '.join(lb.flags.get('A', [])) or '-'} | {', '.join(lb.flags.get('B', [])) or '-'} | "
                f"{_cell(lb.rationale)} |"
            )
        lines.append("")
    return lines


def _fmt(value: float) -> str:
    return "undefined" if math.isnan(value) else f"{value:.3f}"


def _pct(value: float) -> str:
    return "n/a" if math.isnan(value) else f"{value:.0%}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _snippet(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
