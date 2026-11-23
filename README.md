# annotation-qa-kit

Human-data work for frontier AI, built so that **every label is checked by something other than the labeller's opinion**: execution, replay, verbatim source matching, a policy engine, or a second annotator.

| # | Task type | What the annotator does | What checks them | Guidelines | Demo report |
|---|---|---|---|---|---|
| 1 | Pairwise preference (RLHF) | scores two responses on 4 dimensions, flags problems, picks one | 13 consistency rules, alpha/kappa, adjudication queue | [v1](guidelines/pairwise-preference-v1.md) | [report](reports/demo-report.md) |
| 2 | Code evaluation | verdict, 6 scores, issues, **smallest failing input** | hidden tests + the reference implementation run on the annotator's input | [v1](guidelines/code-evaluation-v1.md) | [report](reports/code-demo-report.md) |
| 3 | Factuality / grounding | splits a response into claims, judges each against sources | **verbatim** quote matching, number checks, coverage | [v1](guidelines/factuality-v1.md) | [report](reports/fact-demo-report.md) |
| 4 | Agent trajectories | outcome, first error, policy violations, final-answer faithfulness | **deterministic replay** of the agent's tool calls + **policy-as-code** | [v1](guidelines/agent-trajectory-v1.md) | [report](reports/trajectory-demo-report.md) · [packet](reports/trajectory-packet.md) |
| 5 | Rubric authoring for RL rewards | writes weighted, atomic rubrics with penalties and machine checks | lint, Kendall tau vs known ranking, **reward-hack gap**, grader kappa | [v1](guidelines/rubric-authoring-v1.md) | [report](reports/rubric-demo-report.md) |

Roadmap and research: [`PORTFOLIO_PLAN.md`](PORTFOLIO_PLAN.md). Every planted defect in the data is proven caught by the test suite (`uv run pytest`).

## Task 1: pairwise preference

A toolkit for **pairwise-preference annotation of LLM responses**, the human-feedback data used to train and evaluate AI assistants (RLHF / RLAIF, reward models, model evals).

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

## Task 3: factuality and source checking

Grounding / faithfulness annotation, as used for retrieval-augmented (RAG) systems and summarisation. See [`guidelines/factuality-v1.md`](guidelines/factuality-v1.md).

- **Claim by claim.** An annotator splits the response into atomic claims. Each claim gets a verdict (`supported`, `contradicted`, `not_in_sources` or `opinion`) and, for supported or contradicted claims, a verbatim evidence quote. Every contradicted claim also needs a correction.
- **Mechanical checks** with `annoqa fact-check`:

| Code | Check |
|---|---|
| E303 | the claim is not a verbatim span of the response (an invented claim) |
| E307 | the evidence quote does not occur verbatim in the cited source (a paraphrased or invented quote) |
| E305 / E308 | missing evidence, or a contradiction with no correction |
| W311 | the claims cover less than 80% of the response's sentences (skipped content) |
| W312 | a number in a supported claim is missing from its evidence |
| W313 / W314 | duplicate claims, or evidence attached to an opinion or `not_in_sources` claim |

- **Agreement and gold accuracy.** Claims are aligned across annotators by span overlap, so annotators may split sentences differently. The report shows verdict kappa, factual precision per response, how many gold claims each annotator found, and how many contradictions they caught.
- **The data.** Six items with fictional sources, so every claim is checkable offline. They include a digit swap ($4.2m vs $2.4m), a wrong committee, an outdated source contradicted by a newer one, an unsupported clinical claim the source explicitly rules out, a city swap, a version number error, and a conclusion that inverts its own numbers ("46%, beating its 50% target"). Two decoys look wrong but are right: an attribution that reads reversed and a fair paraphrase.

```bash
uv run annoqa fact-check --items data/facts/items.jsonl data/facts/labels/reference.jsonl \
    examples/synthetic/fact-annotator-b.jsonl --gold ref --out reports/fact-demo-report.md
```

See [`reports/fact-demo-report.md`](reports/fact-demo-report.md).

## Task 4: agent trajectories, verified by replay

An agent run is stored as **calls only**. `annoqa traj-show` replays them in a deterministic office-assistant environment (email, bank, calendar; all fictional) to produce the observations annotators see, so a trajectory can never misreport a tool result. `annoqa traj-check` then scores labels against:
- the **replayed final state**: was the user's goal met? The outcome is `success`, `unsafe_success` (goal met but a policy was broken) or `failure`;
- a **policy engine** (P1 confirmation above $500, P2 no account numbers to outside addresses, P3 no acting on instructions from untrusted emails, i.e. prompt injection, P4 no double-booking), which reports missed and invented violations step by step;
- hidden ground truth for **final-answer faithfulness**, e.g. an agent that sent "$1,750" but reports "$1,250".

The 9 trajectories include a prompt-injection attack, a transposed amount, a skipped confirmation that still "succeeds", and a calendar clash.

```bash
uv run annoqa traj-show --items data/trajectories/items.jsonl --out reports/trajectory-packet.md
uv run annoqa traj-check --items data/trajectories/items.jsonl --hidden data/trajectories/hidden.jsonl \
    data/trajectories/labels/reference.jsonl examples/synthetic/traj-annotator-b.jsonl --gold ref \
    --out reports/trajectory-demo-report.md
```

## Task 5: rubric authoring for rubric-based rewards

In RL with rubric rewards, the rubric *is* the reward function. Each of the 3 tasks ships a deliberately weak **v1** rubric and a revised **v2**, scored on 4 responses of known quality. One of the 4 is a **reward hack**: long, keyword-stuffed and confidently wrong.

| Rubric | Kendall tau vs known order | Hack gap | Hack wins? |
|---|---|---|---|
| v1 (all 3 tasks) | 0.18–0.24 | 0.00 | yes |
| v2 (all 3 tasks) | 1.00 | +1.10 to +1.40 | no |

The linter explains why: v1 uses vague terms, compound criteria, equal weights and no penalties. v2 is atomic, weighted, has `PENALTY:` criteria for known failure modes, and uses machine checks (`includes_any`, `max_words`, `regex`) where possible.

```bash
uv run annoqa rubric-eval --tasks data/rubrics/tasks.jsonl --rubrics data/rubrics/rubrics.jsonl \
    data/rubrics/grades/reference.jsonl examples/synthetic/rubric-grader-b.jsonl --out reports/rubric-demo-report.md
```

The second grader's disagreements are **synthetic** (documented in `scripts/build_rubrics.py`): they illustrate how vague wording splits graders, but they are not a measured result. Measure that with a real second grader.

## About the demo data

- `data/items.jsonl`, `data/code/` and `data/facts/`: original tasks written for this project; all organisations and figures in the factuality sources are fictional. Some responses are deliberately flawed so that the guidelines have something to catch.
- `data/labels/reference.jsonl`: the reference labels (`annotator: "ref"`), labelled under guidelines v1.
- `examples/synthetic/*.jsonl`: **synthetic** second-annotator labels, not human judgments. `scripts/make_synthetic.py`, `build_code_reference.py` and `build_fact_items.py` derive them from the reference labels with documented perturbations, for example a missed flag, a missed bug, a paraphrased quote, an outdated source trusted, or an unextracted claim. They exist only so the demo report has realistic disagreements to show.

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
