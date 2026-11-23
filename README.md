# annotation-qa-kit

A small, rigorous toolkit for **annotating LLM outputs**: pairwise preference between two responses, and code evaluation verified by execution. This is the kind of human-feedback data used to train and evaluate AI assistants (RLHF / RLAIF, reward models, model evals).

It covers the whole quality loop:

1. **Guidelines.** A versioned annotation rubric with definitions, score anchors, a flag taxonomy, preference rules and edge cases. See [`guidelines/pairwise-preference-v1.md`](guidelines/pairwise-preference-v1.md).
2. **Labelled data.** Twelve original prompt / response pairs covering factual errors, buggy code, medical safety, over-refusal, privacy, hallucinated citations, unfaithful summaries, instruction following, translation register and empathy. Each has a fully worked reference label with an evidence-based rationale. See [`data/`](data/).
3. **Validation.** `annoqa validate` catches unusable labels (errors) and internally inconsistent labels (warnings). For example, it warns when someone prefers the response they scored lower, or flags a factual error yet gives full honesty marks.
4. **Agreement.** Krippendorff's alpha (nominal / ordinal / interval, any number of annotators, missing data allowed) and Cohen's kappa (unweighted, linear, quadratic). Both are dependency-free and verified against published values.
5. **Adjudication.** `annoqa report` ranks disagreements by severity and shows each annotator's scores, flags and rationale side by side. It also reports accuracy against a gold annotator.

```bash
uv sync
uv run annoqa validate --items data/items.jsonl data/labels/reference.jsonl
uv run annoqa report --items data/items.jsonl data/labels/reference.jsonl \
    examples/synthetic/annotator-b.jsonl --gold ref --out reports/demo-report.md
uv run pytest
```

See the generated example: [`reports/demo-report.md`](reports/demo-report.md).

## What the validator checks

| Code | Severity | Rule |
|---|---|---|
| E001 | error | `item_id` does not match any item |
| E002 | error | same annotator labelled the same item twice |
| E003 | error | a dimension score is missing or not an integer 1–5 (`"3"` and `true` are rejected) |
| E004 | error | preference is not `A`, `B` or `tie` |
| E005 | error | unknown flag |
| E006 | error | rationale shorter than 15 words |
| E007 | error | empty annotator id |
| W101 | warning | preferred response has a total score 2+ points lower |
| W102 | warning | tie, but totals differ by 3+ |
| W103 | warning | `factual_error` / `hallucinated_source` flagged, yet honesty 4–5 |
| W104 | warning | `unsafe_compliance` / `privacy_risk` flagged, yet harmlessness 4–5 |
| W105 | warning | `over_refusal` flagged, yet helpfulness 4–5 |
| W106 | warning | rationale never names the response it prefers |

Errors exclude a label from agreement statistics. Warnings are kept: a warning can be correct, and the guidelines then require the rationale to say why. Exit codes: `0` clean, `1` errors found (or warnings with `--strict`), `2` bad input.

## How the metrics are verified

- **Krippendorff's alpha** reproduces the worked example in Krippendorff (2011), *Computing Krippendorff's Alpha-Reliability*: nominal 0.743, ordinal 0.815, interval 0.849.
- During development, both metrics were cross-checked against the `krippendorff` and scikit-learn packages on 200 random datasets, matching to 1e-9.
- Undefined statistics (for example, everyone gave the same label) are reported as **undefined**, never as 0 or 1.
- Readings follow Krippendorff (≥ 0.800 reliable, 0.667–0.800 tentative) for alpha, and Landis & Koch (1977) for kappa. They are guides, not proof of quality: the report always lists the actual disagreements.

## Task 2: code evaluation, verified by execution

The second task type grades **one AI-written solution per programming task**, the way coding-annotation projects do. See [`guidelines/code-evaluation-v1.md`](guidelines/code-evaluation-v1.md).

- **Evidence is required.** An annotator gives a verdict (`correct` / `incorrect`) and six 1–5 scores: correctness, edge cases, efficiency, security, readability and explanation accuracy. They also list each issue with a category and severity. An `incorrect` verdict must come with a **failing input**.
- **Verdicts are checked against reality.** `annoqa code-check` runs each solution against hidden tests in a separate Python process, with a timeout and CPU/memory limits. It then runs every failing input an annotator supplies against a trusted reference implementation:

| Code | Meaning |
|---|---|
| V301 | said *correct*, but the hidden tests fail (a missed bug) |
| V302 | said *incorrect*, but the tests pass and no failing input confirms a bug (a false alarm) |
| V303 | the failing input does not actually fail |
| V304 | failing input **confirmed**: the candidate and the reference disagree on it |
| V305 | *incorrect* with no failing input |
| V306 | said *correct*, but another annotator's confirmed failing input exposes a bug |

- **Annotators can find what the tests miss.** In `code-008`, the solution passes all its hidden tests, but `chunk([1, 2], -1)` returns `[]` instead of raising. An annotator who finds that input gets credit for a **test gap**, and the item's ground truth becomes *incorrect*.
- **The data.** Ten original tasks have planted problems: a missing dedup, punctuation ignored by a palindrome check, unsorted merge intervals, an off-by-one binary search, ties broken in the wrong order, path traversal, a negative-size test gap, O(n²) on a stated 100k input, and a dropped last window. Two candidates are genuinely correct. `tests/test_code_eval.py` proves exactly which candidates fail which tests.

```bash
uv run annoqa code-check --items data/code/items.jsonl data/code/labels/reference.jsonl \
    examples/synthetic/code-annotator-b.jsonl --gold ref --out reports/code-demo-report.md
```

See [`reports/code-demo-report.md`](reports/code-demo-report.md).

The sandbox isolates *known sample code* for checking correctness. It is **not** a security boundary for running untrusted code.

## About the demo data

- `data/items.jsonl`: original prompts and responses written for this project. Some responses are deliberately flawed so that the guidelines have something to catch.
- `data/labels/reference.jsonl`: the reference labels (`annotator: "ref"`), labelled under guidelines v1.
- `examples/synthetic/annotator-b.jsonl` and `code-annotator-b.jsonl`: **synthetic** second-annotator labels, not human judgments. `scripts/make_synthetic.py` makes them from the reference labels with seeded, documented perturbations: score noise, a missed flag, one preference flip, one inconsistent label and one too-short rationale. They exist only so the demo report has realistic disagreements to show.

To measure real agreement, have a second person label `data/items.jsonl` under the guidelines and run `annoqa report` on both files.

## Label format

One JSON object per line:

```json
{"item_id": "it-005", "annotator": "alice", "preference": "A",
 "scores": {"A": {"instruction_following": 5, "helpfulness": 5, "honesty": 5, "harmlessness": 5},
            "B": {"instruction_following": 4, "helpfulness": 1, "honesty": 1, "harmlessness": 5}},
 "flags": {"A": [], "B": ["factual_error"]},
 "rationale": "A is correct: 40 x 0.75 = 30, then 30 x 1.10 = 33. B nets the percentages to 15% off and gets $34, which is wrong."}
```

## License

MIT
