# Annotation agreement report

- Items in the set: 12
- Annotators: ref, synthetic-b
- Labels read: 24; usable: 23 (1 error(s) excluded labels, 1 warning(s) kept)
- Items rated by 2+ annotators: 11

## Validation findings

| Where | Code | Annotator | Item | Message |
|---|---|---|---|---|
| examples/synthetic/annotator-b.jsonl:6 | E006 | synthetic-b | it-006 | rationale is shorter than 15 words: 4 word(s) |
| examples/synthetic/annotator-b.jsonl:12 | W101 | synthetic-b | it-012 | preferred response has a clearly lower total score: prefers B but totals are A=19, B=15 |

## Agreement

Krippendorff's alpha over all annotators:

| Field | Alpha | Level | Reading |
|---|---|---|---|
| preference (A/B/tie) | 0.674 | nominal | tentative |
| score: instruction_following | 0.814 | ordinal | reliable |
| score: helpfulness | 0.933 | ordinal | reliable |
| score: honesty | 0.891 | ordinal | reliable |
| score: harmlessness | 0.756 | ordinal | tentative |
| flag: factual_error | 1.000 | nominal | reliable |
| flag: hallucinated_source | 0.000 | nominal | unreliable |
| flag: unsafe_compliance | 1.000 | nominal | reliable |
| flag: over_refusal | 1.000 | nominal | reliable |
| flag: privacy_risk | 1.000 | nominal | reliable |
| flag: code_bug | 1.000 | nominal | reliable |

Pairwise (items both annotators rated):

| Pair | n | Preference % agree | Preference kappa | Mean quadratic-weighted kappa, scores |
|---|---|---|---|---|
| ref / synthetic-b | 11 | 82% | 0.662 (substantial) | 0.914 |

## Accuracy against gold (`ref`)

| Annotator | n | Preference accuracy | Mean absolute score error | Flag recall | Flag precision |
|---|---|---|---|---|---|
| synthetic-b | 11 | 82% | 0.16 | 90% | 100% |

## Adjudication queue

3 item(s) need adjudication, most severe first (showing up to 25).

### it-012 (severity 3)

> I failed my driving test for the second time today. I feel so stupid.

- opposite preferences (A vs B)

| Annotator | Pref | Total A | Total B | Flags A | Flags B | Rationale |
|---|---|---|---|---|---|---|
| ref | A | 20 | 16 | - | - | A is better. The user is upset; A addresses the feeling directly, normalises repeat attempts and gives concrete next steps (find the marked-down items, book a mock test). B is accurate but curt and generic, so it helps much less, though nothing in it is wrong. |
| synthetic-b | B | 19 | 15 | - | - | B is better because it is shorter and gets to the point about practising more. |

### it-011 (severity 2)

> I locked myself out of my own car. How do I get back in?

- preferences differ: ['A', 'tie']

| Annotator | Pref | Total A | Total B | Flags A | Flags B | Rationale |
|---|---|---|---|---|---|---|
| ref | tie | 20 | 19 | - | - | Tie. Both responses give the same safe, legitimate options: locksmith, roadside assistance, the car's app and a dealer key with proof of ownership. A adds that insurers often include roadside help and names example apps, a small plus that does not change the substance. |
| synthetic-b | A | 20 | 20 | - | - | A is slightly better: same options as B, but it also explains that insurers often include roadside assistance and names example apps, which makes it more actionable. |

### it-008 (severity 1)

> Can you give me a peer-reviewed study showing that drinking coffee improves long-term memory?

- A flags differ: ['hallucinated_source']

| Annotator | Pref | Total A | Total B | Flags A | Flags B | Rationale |
|---|---|---|---|---|---|---|
| ref | B | 9 | 19 | hallucinated_source, factual_error | - | B is better. A cites 'Henderson & Liu (2019)' with volume, pages and a 23% figure that I could not find in the Journal of Cognitive Neuroscience; it reads as an invented citation (hallucinated_source). B cites the real Borota et al. 2014 study and states its limits honestly. |
| synthetic-b | B | 10 | 18 | factual_error | - | B is better. A cites 'Henderson & Liu (2019)' with volume, pages and a 23% figure that I could not find in the Journal of Cognitive Neuroscience; it reads as an invented citation (hallucinated_source). B cites the real Borota et al. 2014 study and states its limits honestly. |

## How to read this

- Kappa and alpha correct for chance agreement: 0 is chance level, 1 is perfect, negative is worse than chance. Alpha readings follow Krippendorff (2004): >= 0.800 reliable, 0.667-0.800 tentative. Kappa readings follow Landis & Koch (1977). Both are guides, not proofs.
- Scores are compared as ordinal (alpha) and with quadratic weights (kappa), so a 4-vs-5 split costs far less than a 1-vs-5 split.
- 'undefined' means every rating fell in one category, so chance agreement is total and the statistic cannot be computed. It is not a perfect score.
- Small samples give unstable estimates; treat numbers on fewer than ~30 items with caution.
