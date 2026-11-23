"""Claim-level factuality annotation against provided sources (grounding / RAG faithfulness).

An annotator splits a response into atomic claims, gives each a verdict, and backs
every 'supported' or 'contradicted' verdict with a quote from a source. The checker
verifies mechanically what can be verified:

- each claim is a verbatim span of the response (no invented claims);
- each evidence quote occurs verbatim in the source it cites (no invented evidence);
- numbers in a 'supported' claim appear in its evidence;
- the claims cover the response (no silently skipped sentences).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from annoqa.agreement import cohen_kappa, interpret_kappa, percent_agreement
from annoqa.schema import LoadError, read_jsonl

VERDICTS: tuple[str, ...] = ("supported", "contradicted", "not_in_sources", "opinion")
NEEDS_EVIDENCE = ("supported", "contradicted")
MIN_COVERAGE = 0.8
MATCH_THRESHOLD = 0.5

Kind = Literal["error", "warning"]

RULES: dict[str, tuple[Kind, str]] = {
    "E301": ("error", "item_id does not match any factuality item"),
    "E302": ("error", "same annotator labelled the same item twice"),
    "E303": ("error", "claim text is not a verbatim span of the response"),
    "E304": ("error", "verdict must be supported, contradicted, not_in_sources or opinion"),
    "E305": ("error", "supported/contradicted claim has no evidence"),
    "E306": ("error", "evidence cites a source id the item does not have"),
    "E307": ("error", "evidence quote does not occur verbatim in the cited source"),
    "E308": ("error", "contradicted claim has no correction"),
    "E309": ("error", "annotator id is empty or claims is not a list"),
    "W311": ("warning", f"claims cover less than {MIN_COVERAGE:.0%} of the response's sentences"),
    "W312": ("warning", "a number in a supported claim does not appear in its evidence"),
    "W313": ("warning", "two claims overlap heavily (duplicate or not atomic)"),
    "W314": ("warning", "not_in_sources/opinion claim carries evidence (did you mean supported/contradicted?)"),
}


@dataclass(frozen=True)
class FactItem:
    id: str
    question: str
    response: str
    sources: dict[str, str]  # id -> text
    titles: dict[str, str] = field(default_factory=dict)


@dataclass
class FactLabel:
    item_id: str
    annotator: str
    claims: Any
    rationale: str = ""
    line: int = 0
    source: str = ""


@dataclass(frozen=True)
class FactFinding:
    code: str
    item_id: str
    annotator: str
    message: str
    where: str

    @property
    def kind(self) -> Kind:
        return RULES[self.code][0]


def load_fact_items(path: Path) -> dict[str, FactItem]:
    items: dict[str, FactItem] = {}
    for n, obj in read_jsonl(path):
        try:
            sources = {str(s["id"]): str(s["text"]) for s in obj["sources"]}
            titles = {str(s["id"]): str(s.get("title", "")) for s in obj["sources"]}
            item = FactItem(str(obj["id"]), str(obj["question"]), str(obj["response"]), sources, titles)
        except (KeyError, TypeError) as exc:
            raise LoadError(f"{path}:{n}: malformed factuality item ({exc})") from exc
        if item.id in items:
            raise LoadError(f"{path}:{n}: duplicate item id {item.id!r}")
        items[item.id] = item
    return items


def load_fact_labels(path: Path) -> list[FactLabel]:
    return [
        FactLabel(
            item_id=str(obj.get("item_id", "")),
            annotator=str(obj.get("annotator", "")),
            claims=obj.get("claims"),
            rationale=str(obj.get("rationale", "")),
            line=n,
            source=str(path),
        )
        for n, obj in read_jsonl(path)
    ]


def normalize(text: str) -> str:
    """Whitespace- and quote-insensitive form used for verbatim checks; case is kept."""
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(text.split())


def numbers(text: str) -> set[str]:
    return {m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [p for p in parts if p]


def span_of(claim: str, response: str) -> tuple[int, int] | None:
    norm_resp, norm_claim = normalize(response), normalize(claim)
    start = norm_resp.find(norm_claim) if norm_claim else -1
    return None if start < 0 else (start, start + len(norm_claim))


def overlap(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def coverage(spans: list[tuple[int, int]], response: str) -> tuple[float, list[str]]:
    norm = normalize(response)
    missed: list[str] = []
    sents = sentences(norm)
    pos = 0
    for s in sents:
        start = norm.find(s, pos)
        end = start + len(s)
        pos = end
        if not any(overlap((start, end), sp) > 0 for sp in spans):
            missed.append(s)
    return (1 - len(missed) / len(sents) if sents else 1.0), missed


def check(labels: list[FactLabel], items: dict[str, FactItem]) -> list[FactFinding]:
    findings: list[FactFinding] = []
    seen: set[tuple[str, str]] = set()
    for lb in labels:

        def add(code: str, detail: str = "", lb: FactLabel = lb) -> None:
            msg = RULES[code][1] + (f": {detail}" if detail else "")
            where = f"{lb.source}:{lb.line}" if lb.source else f"line {lb.line}"
            findings.append(FactFinding(code, lb.item_id, lb.annotator, msg, where))

        item = items.get(lb.item_id)
        if item is None:
            add("E301", repr(lb.item_id))
        if (lb.item_id, lb.annotator) in seen:
            add("E302")
        seen.add((lb.item_id, lb.annotator))
        if not lb.annotator.strip() or not isinstance(lb.claims, list):
            add("E309")
            continue
        if item is None:
            continue
        spans: list[tuple[int, int]] = []
        for n, c in enumerate(lb.claims, start=1):
            c = c if isinstance(c, dict) else {}
            text = str(c.get("text", ""))
            tag = f"claim {n} {text[:50]!r}"
            sp = span_of(text, item.response)
            if sp is None:
                add("E303", tag)
            else:
                spans.append(sp)
            verdict = c.get("verdict")
            if verdict not in VERDICTS:
                add("E304", f"{tag}: {verdict!r}")
            raw_evidence = c.get("evidence")
            evidence: list[Any] = raw_evidence if isinstance(raw_evidence, list) else []
            if verdict in NEEDS_EVIDENCE and not evidence:
                add("E305", tag)
            if verdict in ("not_in_sources", "opinion") and evidence:
                add("W314", tag)
            quotes = []
            for ev in evidence:
                ev = ev if isinstance(ev, dict) else {}
                sid, quote = str(ev.get("source", "")), str(ev.get("quote", ""))
                if sid not in item.sources:
                    add("E306", f"{tag}: {sid!r}")
                elif not quote.strip() or normalize(quote) not in normalize(item.sources[sid]):
                    add("E307", f"{tag}: {quote[:60]!r} not in {sid}")
                else:
                    quotes.append(quote)
            if verdict == "contradicted" and not str(c.get("correction", "")).strip():
                add("E308", tag)
            if verdict == "supported" and quotes:
                missing = numbers(text) - set().union(*(numbers(q) for q in quotes))
                if missing:
                    add("W312", f"{tag}: {sorted(missing)}")
        for (i, a), (j, b) in combinations(enumerate(spans, start=1), 2):
            if overlap(a, b) >= 0.8:
                add("W313", f"claims {i} and {j}")
        cov, missed = coverage(spans, item.response)
        if cov < MIN_COVERAGE:
            add("W311", f"{cov:.0%}; unclaimed: " + " | ".join(m[:60] for m in missed))
    return findings


@dataclass(frozen=True)
class Aligned:
    item_id: str
    text: str
    verdicts: dict[str, str]  # annotator -> verdict, or "(not extracted)"


NOT_EXTRACTED = "(not extracted)"


def align(labels: list[FactLabel], items: dict[str, FactItem]) -> list[Aligned]:
    """Match claims across annotators by span overlap; unmatched claims count as not extracted."""
    out: list[Aligned] = []
    by_item: dict[str, list[FactLabel]] = {}
    for lb in labels:
        if lb.item_id in items and isinstance(lb.claims, list):
            by_item.setdefault(lb.item_id, []).append(lb)
    for item_id, lbs in by_item.items():
        response = items[item_id].response
        annotators = [lb.annotator for lb in lbs]
        groups: list[tuple[tuple[int, int], str, dict[str, str]]] = []
        for lb in lbs:
            for c in lb.claims:
                if not isinstance(c, dict):
                    continue
                sp = span_of(str(c.get("text", "")), response)
                if sp is None:
                    continue
                best = max(groups, key=lambda g: overlap(g[0], sp), default=None)
                if best is not None and overlap(best[0], sp) >= MATCH_THRESHOLD and lb.annotator not in best[2]:
                    best[2][lb.annotator] = str(c.get("verdict"))
                else:
                    groups.append((sp, str(c.get("text", "")), {lb.annotator: str(c.get("verdict"))}))
        for _sp, text, verdicts in sorted(groups, key=lambda g: g[0]):
            out.append(Aligned(item_id, text, {a: verdicts.get(a, NOT_EXTRACTED) for a in annotators}))
    return out


def precision(lb: FactLabel) -> float:
    """Share of checkable claims that are supported (opinions excluded)."""
    verdicts = [c.get("verdict") for c in lb.claims if isinstance(c, dict)]
    checkable = [v for v in verdicts if v in ("supported", "contradicted", "not_in_sources")]
    return sum(v == "supported" for v in checkable) / len(checkable) if checkable else math.nan


def build_fact_report(labels: list[FactLabel], items: dict[str, FactItem], *, gold: str | None = None) -> str:
    findings = check(labels, items)
    bad = {(f.item_id, f.annotator) for f in findings if f.kind == "error"}
    good = [lb for lb in labels if (lb.item_id, lb.annotator) not in bad]
    annotators = sorted({lb.annotator for lb in good})
    lines = [
        "# Factuality report",
        "",
        f"- Items: {len(items)}; labels read: {len(labels)}; usable: {len(good)} (labels with errors are excluded)",
        f"- Annotators: {', '.join(annotators) or 'none'}",
        "",
        "## Response factual precision (supported / checkable claims)",
        "",
        "| Item | " + " | ".join(annotators) + " |",
        "|---|" + "---|" * len(annotators),
    ]
    for item_id in items:
        row = [item_id]
        for a in annotators:
            lb = next((x for x in good if x.item_id == item_id and x.annotator == a), None)
            row.append("-" if lb is None else _pct(precision(lb)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    aligned = align(good, items)
    if len(annotators) >= 2:
        lines += [
            "## Claim agreement",
            "",
            "| Pair | Claims matched | Same verdict | Verdict kappa |",
            "|---|---|---|---|",
        ]
        for x, y in combinations(annotators, 2):
            both = [
                c
                for c in aligned
                if c.verdicts.get(x, NOT_EXTRACTED) != NOT_EXTRACTED
                and c.verdicts.get(y, NOT_EXTRACTED) != NOT_EXTRACTED
            ]
            if both:
                vx, vy = [c.verdicts[x] for c in both], [c.verdicts[y] for c in both]
                k = cohen_kappa(vx, vy, categories=VERDICTS)
                lines.append(
                    f"| {x} / {y} | {len(both)} | {percent_agreement(vx, vy):.0%} | {_fmt(k)} ({interpret_kappa(k)}) |"
                )
        lines.append("")
    if gold and gold in annotators:
        lines += [
            f"## Against gold (`{gold}`)",
            "",
            "| Annotator | Gold claims found | Verdict accuracy on found | Contradictions caught |",
            "|---|---|---|---|",
        ]
        for a in annotators:
            if a == gold:
                continue
            gold_claims = [
                c for c in aligned if c.verdicts.get(gold, NOT_EXTRACTED) != NOT_EXTRACTED and a in c.verdicts
            ]
            found = [c for c in gold_claims if c.verdicts[a] != NOT_EXTRACTED]
            correct = sum(c.verdicts[a] == c.verdicts[gold] for c in found)
            contra = [c for c in gold_claims if c.verdicts[gold] == "contradicted"]
            caught = sum(c.verdicts[a] == "contradicted" for c in contra)
            acc = _pct(correct / len(found) if found else math.nan)
            lines.append(f"| {a} | {len(found)}/{len(gold_claims)} | {acc} | {caught}/{len(contra)} |")
        lines.append("")

    disagreements = [c for c in aligned if len(set(c.verdicts.values())) > 1]
    lines += ["## Adjudication queue", ""]
    if not disagreements:
        lines.append("No claim-level disagreements.")
    else:
        lines += ["| Item | Claim | " + " | ".join(annotators) + " |", "|---|---|" + "---|" * len(annotators)]
        for c in disagreements:
            cells = [c.verdicts.get(a, "-") for a in annotators]
            lines.append(f"| {c.item_id} | {_cell(c.text)} | " + " | ".join(cells) + " |")
    lines += ["", "## Findings", ""]
    if not findings:
        lines.append("No findings.")
    else:
        lines += ["| Where | Code | Kind | Annotator | Item | Message |", "|---|---|---|---|---|---|"]
        for f in sorted(findings, key=lambda f: (f.kind != "error", f.item_id, f.annotator)):
            lines.append(f"| {f.where} | {f.code} | {f.kind} | {f.annotator} | {f.item_id} | {_cell(f.message)} |")
    lines += [
        "",
        "## How to read this",
        "",
        "- Every evidence quote was checked to occur verbatim in its cited source; "
        "paraphrased or invented evidence is an error.",
        "- 'Gold claims found' measures decomposition: a contradiction the annotator never extracted "
        "is a missed error, the costliest mistake in factuality data.",
        "- Claims are matched across annotators by span overlap (>= 50%), "
        "so annotators may split sentences differently.",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: float) -> str:
    return "undefined" if math.isnan(value) else f"{value:.3f}"


def _pct(value: float) -> str:
    return "n/a" if math.isnan(value) else f"{value:.0%}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
