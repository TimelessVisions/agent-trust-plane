"""Write the factuality task data.

- data/facts/items.jsonl: a question, source documents and an AI response to fact-check.
- data/facts/labels/reference.jsonl: reference claim-level labels.
- examples/synthetic/fact-annotator-b.jsonl: SYNTHETIC second annotator (documented perturbations).

All organisations, people and figures in the sources are FICTIONAL, written for this
project, so every claim can be checked against the sources alone with no outside lookup.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

ITEMS: list[dict[str, Any]] = [
    {
        "id": "fact-001",
        "question": "What did the Larkfield council decide about the Main Street bike lane?",
        "sources": [
            {
                "id": "S1",
                "title": "Larkfield Gazette, 14 March 2026",
                "text": "The Larkfield town council voted 5-4 on Tuesday to delay construction of the Main Street "
                "bike lane until April 2027. Councillor Dana Ortiz, who chairs the transport committee, said the "
                "delay was needed because the project's cost estimate had risen to $2.4 million. Supporters argued "
                "that delaying would add roughly $300,000 in inflation costs.",
            }
        ],
        "response": "The Larkfield council voted 5-4 to delay the Main Street bike lane until April 2027. "
        "The decision was driven by a cost estimate that had risen to $4.2 million. "
        "Councillor Dana Ortiz, who chairs the finance committee, defended the delay. "
        "Critics of the delay warned it could add about $300,000 in costs. "
        "Overall, it was a sensible compromise.",
    },
    {
        "id": "fact-002",
        "question": "When does the Brightwater Library open on weekends, and does it have parking?",
        "sources": [
            {
                "id": "S1",
                "title": "Brightwater Library: visitor information (updated 2 June 2026)",
                "text": "Opening hours: Monday to Friday 9:00-20:00; Saturday 10:00-17:00; Sunday 12:00-16:00. "
                "The library has 40 free parking spaces, including 4 accessible spaces. Parking is limited to "
                "three hours.",
            },
            {
                "id": "S2",
                "title": "Brightwater Library: visitor information (archived, January 2024)",
                "text": "Opening hours: Monday to Friday 9:00-19:00; Saturday 10:00-16:00; closed on Sundays. "
                "There are 25 free parking spaces.",
            },
        ],
        "response": "On weekends the library opens Saturday 10:00-17:00 and Sunday 12:00-16:00. "
        "It has 25 free parking spaces. Parking is limited to three hours. "
        "The library also offers free Wi-Fi throughout the building.",
    },
    {
        "id": "fact-003",
        "question": "Summarise the results of the Norvale clinical trial for the drug Kelotrin.",
        "sources": [
            {
                "id": "S1",
                "title": "Norvale Research Institute press release, 9 September 2026",
                "text": "In a 12-week trial of 480 adults with mild hypertension, Kelotrin lowered systolic blood "
                "pressure by an average of 8 mmHg compared with placebo. The most common side effect was "
                "headache, reported by 11% of participants taking Kelotrin. The trial was not designed to "
                "measure effects on heart attacks or strokes. Regulators have not yet approved the drug.",
            }
        ],
        "response": "The Norvale trial enrolled 480 adults with mild hypertension over 12 weeks. "
        "Kelotrin lowered systolic blood pressure by about 8 mmHg versus placebo. "
        "Headache was the most common side effect, affecting 11% of participants on the drug. "
        "The trial also showed Kelotrin reduces the risk of heart attacks. "
        "Kelotrin is expected to be approved next year.",
    },
    {
        "id": "fact-004",
        "question": "Who founded Quillon Robotics and what does it make?",
        "sources": [
            {
                "id": "S1",
                "title": "Quillon Robotics: about us",
                "text": "Quillon Robotics was founded in 2019 by Priya Raman and Tomas Lindqvist in Gothenburg, "
                "Sweden. The company makes autonomous robots for inspecting wind turbine blades. It employs "
                "around 140 people.",
            }
        ],
        "response": "Quillon Robotics was founded in 2019 by Priya Raman and Tomas Lindqvist. "
        "It is based in Stockholm, Sweden. "
        "The company builds autonomous robots that inspect wind turbine blades. "
        "It has around 140 employees.",
    },
    {
        "id": "fact-005",
        "question": "What changed in version 3.0 of the Fernhill data export tool?",
        "sources": [
            {
                "id": "S1",
                "title": "Fernhill Export 3.0 release notes",
                "text": "Version 3.0 adds export to Parquet and removes the deprecated XML exporter. The default "
                "batch size changes from 500 to 1,000 rows. Python 3.9 is no longer supported; the minimum "
                "version is now Python 3.11.",
            }
        ],
        "response": "Version 3.0 adds Parquet export. "
        "It also removes the old XML exporter. "
        "The default batch size doubles from 500 to 1,000 rows. "
        "The minimum supported Python version is now 3.10.",
    },
    {
        "id": "fact-006",
        "question": "How did Harrowgate's 2025 recycling rate compare with its target?",
        "sources": [
            {
                "id": "S1",
                "title": "Harrowgate District annual waste report 2025",
                "text": "The district recycled 46% of household waste in 2025, up from 41% in 2024. The target "
                "for 2025 was 50%. Food waste collection, introduced in May 2025, accounted for most of the "
                "increase.",
            }
        ],
        "response": "Harrowgate recycled 46% of household waste in 2025, beating its 50% target. "
        "That was up from 41% the year before. "
        "Most of the increase came from the new food waste collection introduced in May 2025.",
    },
]


def claim(
    text: str, verdict: str, evidence: list[tuple[str, str]] | None = None, correction: str = ""
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "text": text,
        "verdict": verdict,
        "evidence": [{"source": s, "quote": q} for s, q in (evidence or [])],
    }
    if correction:
        out["correction"] = correction
    return out


REFERENCE: dict[str, list[dict[str, Any]]] = {
    "fact-001": [
        claim(
            "voted 5-4 to delay the Main Street bike lane until April 2027",
            "supported",
            [("S1", "voted 5-4 on Tuesday to delay construction of the Main Street bike lane until April 2027")],
        ),
        claim(
            "a cost estimate that had risen to $4.2 million",
            "contradicted",
            [("S1", "the project's cost estimate had risen to $2.4 million")],
            "The estimate rose to $2.4 million, not $4.2 million.",
        ),
        claim(
            "Councillor Dana Ortiz, who chairs the finance committee",
            "contradicted",
            [("S1", "Councillor Dana Ortiz, who chairs the transport committee")],
            "Ortiz chairs the transport committee.",
        ),
        claim(
            "Critics of the delay warned it could add about $300,000 in costs",
            "supported",
            [("S1", "Supporters argued that delaying would add roughly $300,000 in inflation costs")],
        ),
        claim("Overall, it was a sensible compromise.", "opinion"),
    ],
    "fact-002": [
        claim(
            "Saturday 10:00-17:00 and Sunday 12:00-16:00",
            "supported",
            [("S1", "Saturday 10:00-17:00; Sunday 12:00-16:00")],
        ),
        claim(
            "It has 25 free parking spaces.",
            "contradicted",
            [("S1", "The library has 40 free parking spaces")],
            "The current page (June 2026) lists 40 spaces; 25 is from the archived 2024 page.",
        ),
        claim("Parking is limited to three hours.", "supported", [("S1", "Parking is limited to three hours.")]),
        claim("The library also offers free Wi-Fi throughout the building.", "not_in_sources"),
    ],
    "fact-003": [
        claim(
            "enrolled 480 adults with mild hypertension over 12 weeks",
            "supported",
            [("S1", "In a 12-week trial of 480 adults with mild hypertension")],
        ),
        claim(
            "lowered systolic blood pressure by about 8 mmHg versus placebo",
            "supported",
            [("S1", "lowered systolic blood pressure by an average of 8 mmHg compared with placebo")],
        ),
        claim(
            "Headache was the most common side effect, affecting 11% of participants on the drug",
            "supported",
            [("S1", "The most common side effect was headache, reported by 11% of participants taking Kelotrin")],
        ),
        claim(
            "The trial also showed Kelotrin reduces the risk of heart attacks.",
            "contradicted",
            [("S1", "The trial was not designed to measure effects on heart attacks or strokes.")],
            "The trial did not measure heart attacks at all.",
        ),
        claim("Kelotrin is expected to be approved next year.", "not_in_sources"),
    ],
    "fact-004": [
        claim(
            "founded in 2019 by Priya Raman and Tomas Lindqvist",
            "supported",
            [("S1", "founded in 2019 by Priya Raman and Tomas Lindqvist")],
        ),
        claim(
            "It is based in Stockholm, Sweden.",
            "contradicted",
            [("S1", "in Gothenburg, Sweden")],
            "It was founded in Gothenburg; the sources never mention Stockholm.",
        ),
        claim(
            "builds autonomous robots that inspect wind turbine blades",
            "supported",
            [("S1", "makes autonomous robots for inspecting wind turbine blades")],
        ),
        claim("It has around 140 employees.", "supported", [("S1", "It employs around 140 people.")]),
    ],
    "fact-005": [
        claim("Version 3.0 adds Parquet export.", "supported", [("S1", "Version 3.0 adds export to Parquet")]),
        claim("It also removes the old XML exporter.", "supported", [("S1", "removes the deprecated XML exporter")]),
        claim(
            "The default batch size doubles from 500 to 1,000 rows.",
            "supported",
            [("S1", "The default batch size changes from 500 to 1,000 rows.")],
        ),
        claim(
            "The minimum supported Python version is now 3.10.",
            "contradicted",
            [("S1", "the minimum version is now Python 3.11")],
            "The minimum is Python 3.11.",
        ),
    ],
    "fact-006": [
        claim(
            "Harrowgate recycled 46% of household waste in 2025",
            "supported",
            [("S1", "The district recycled 46% of household waste in 2025")],
        ),
        claim(
            "beating its 50% target",
            "contradicted",
            [("S1", "The target for 2025 was 50%.")],
            "46% is below the 50% target, so the target was missed.",
        ),
        claim("That was up from 41% the year before.", "supported", [("S1", "up from 41% in 2024")]),
        claim(
            "Most of the increase came from the new food waste collection introduced in May 2025.",
            "supported",
            [("S1", "Food waste collection, introduced in May 2025, accounted for most of the increase.")],
        ),
    ],
}

RATIONALES = {
    "fact-001": "Two contradictions: the cost figure has its digits swapped ($4.2m vs $2.4m) and Ortiz chairs the transport, not finance, committee. The $300,000 warning came from supporters of the lane, i.e. critics of the delay, so that claim holds. The last sentence is opinion.",
    "fact-002": "Weekend hours and the parking time limit match the current page. The parking count comes from the archived 2024 page and is outdated: the newer source wins. Free Wi-Fi is not mentioned in either source.",
    "fact-003": "The trial facts are accurate, but the heart-attack claim directly contradicts the release, which says the trial was not designed to measure that. The approval forecast is not in the source; it says only that the drug is not yet approved.",
    "fact-004": "Founders, year, product and headcount are supported. The location is wrong: the source says Gothenburg. Stockholm appears nowhere and looks like a plausible-sounding substitution.",
    "fact-005": "Three of four changes are accurate, and doubling from 500 to 1,000 is a fair paraphrase. The Python minimum is wrong: the notes say 3.11, and 3.10 is never mentioned.",
    "fact-006": "The figures are copied correctly, but the conclusion inverts them: 46% is below the 50% target, so the response's 'beating its target' is contradicted by its own numbers and the source.",
}


def reference_rows() -> list[dict[str, Any]]:
    return [{"item_id": i, "annotator": "ref", "claims": REFERENCE[i], "rationale": RATIONALES[i]} for i in REFERENCE]


def synthetic(ref: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Seeded-by-hand, documented perturbations of the reference. Not human judgments."""
    b = copy.deepcopy(ref)
    by = {r["item_id"]: r for r in b}
    for r in b:
        r["annotator"] = "synthetic-b"
    # Misses the outdated-source trap: trusts the archived page.
    c = by["fact-002"]["claims"][1]
    c.update(verdict="supported", evidence=[{"source": "S2", "quote": "There are 25 free parking spaces."}])
    c.pop("correction")
    # Misses the inverted conclusion entirely: never extracts that claim.
    by["fact-006"]["claims"].pop(1)
    # Paraphrases the evidence instead of quoting it (the validator must reject this).
    by["fact-004"]["claims"][2]["evidence"][0]["quote"] = "The company builds robots that inspect turbine blades."
    # Reasonable judgment difference: treats the approval forecast as opinion.
    by["fact-003"]["claims"][4]["verdict"] = "opinion"
    return b


def main() -> None:
    ref = reference_rows()
    outputs = {
        ROOT / "data/facts/items.jsonl": ITEMS,
        ROOT / "data/facts/labels/reference.jsonl": ref,
        ROOT / "examples/synthetic/fact-annotator-b.jsonl": synthetic(ref),
    }
    for path, rows in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"wrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
