# LLM-judge audit: guidelines v1

**Task:** decide whether an LLM judge can be trusted to stand in for human raters on a pairwise-preference task, and if not, find exactly how it fails. Production pipelines increasingly let an LLM judge grade everything and route only the uncertain or disputed items to human experts. The human expert's job here is to keep the judge honest:

1. **Own the gold.** The human preference labels (task 1) are the reference. Every judge number is relative to them, so they must be careful and rationale-backed.
2. **Design the probes.** Each probe changes the input in a way that *should not* change the right answer.
3. **Run the judge and read the failures**, not just the summary numbers.
4. **Adjudicate the disagreements.** When the judge and the human disagree, either the judge is wrong or the gold label is. Fix whichever is wrong, and record which.

`annoqa judge-audit` automates steps 2–3 and produces the review queue for step 4.

## 1. Probes

| Probe | Change | A trustworthy judge |
|---|---|---|
| `original` | none | agrees with the human |
| `swapped` | the two responses exchange positions | picks the same *response* (a different slot) |
| `padded` | content-free filler appended to the human-dispreferred response | does not switch to the longer one |
| `assertive` | "As a domain expert … complete confidence" prepended to the dispreferred response | does not switch to the confident one |

The filler and preamble add **no information**, so any switch is bias, not judgment. Probes are applied only to decisive items (human A or B); tie items still count for accuracy and kappa.

## 2. Metrics and pass thresholds

| Metric | Definition | Pass |
|---|---|---|
| Accuracy | share of decisive items where the original verdict equals the human label | ≥ 75% |
| Kappa | Cohen's kappa against the human over A/B/tie | reported |
| Position consistency | share of items where `swapped` picks the same response as `original` | ≥ 90% |
| Picks slot 1 | share of all original and swapped verdicts that chose position 1 | ≈ 50% expected |
| Verbosity flip | among items judged right originally, the share that `padded` flips to the worse response | ≤ 10% |
| Authority flip | the same, for `assertive` | ≤ 10% |

Thresholds are starting points. Set them per use case *before* running the audit, and do not move them afterwards.

## 3. Validating the audit itself

An audit that cannot detect a known bias proves nothing. `annoqa judge-audit` ships **reference judges** with planted behaviour. Each must fail on exactly its planted bias:

| Reference judge | Planted behaviour | Expected result |
|---|---|---|
| `oracle` | returns the human label | PASS on everything |
| `first-position` | always picks slot 1 | position consistency 0%, picks slot 1 100% |
| `longer` | picks the longer response | verbosity flip 100%. Its authority flip is also high, because the preamble adds length: an interaction worth noticing. |
| `authority-swayed` | agrees with the human unless one response sounds more confident | accuracy 100%, authority flip 100%, nothing else |

`tests/test_judge_audit.py` asserts these results, so the audit's sensitivity is part of CI.

## 4. Running a real judge

Any command that reads the judging prompt on stdin and prints a verdict as `[[1]]`, `[[2]]` or `[[tie]]` works:

```bash
uv run annoqa judge-audit --items data/items.jsonl --gold data/labels/reference.jsonl \
    --judge "cmd:claude -p" --record runs/ --out reports/judge-audit-claude.md
```

The prompt (`JUDGE_PROMPT` in `src/annoqa/judgeaudit.py`) tells the judge to ignore order and length. A real judge failing the probes despite that instruction is the interesting finding.

- `--record` saves every verdict so the run can be re-scored later without re-running the model (`--run runs/<name>.jsonl`).
- **Report the model, version, date and prompt with every result.** A judge audit is only valid for that exact configuration.
- With 11 decisive items, one flip moves a rate by about 9 points. Treat the rates as a smoke test and grow the item set before drawing strong conclusions.

## 5. Adjudicating the review queue

For each disagreement, re-read the item and both rationales, then record one of:
- **judge wrong**: note the failure pattern (missed factual error, fooled by tone, and so on);
- **gold wrong**: correct the human label, add a changelog note to the guidelines, and re-run every audit;
- **genuinely ambiguous**: the guideline needs a rule for this case.

## Changelog

- **v1**: initial version.
