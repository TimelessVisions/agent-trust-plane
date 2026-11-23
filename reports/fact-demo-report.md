# Factuality report

- Items: 6; labels read: 12; usable: 11 (labels with errors are excluded)
- Annotators: ref, synthetic-b

## Response factual precision (supported / checkable claims)

| Item | ref | synthetic-b |
|---|---|---|
| fact-001 | 50% | 50% |
| fact-002 | 50% | 75% |
| fact-003 | 60% | 75% |
| fact-004 | 75% | - |
| fact-005 | 75% | 75% |
| fact-006 | 75% | 100% |

## Claim agreement

| Pair | Claims matched | Same verdict | Verdict kappa |
|---|---|---|---|
| ref / synthetic-b | 21 | 90% | 0.821 (almost perfect) |

## Against gold (`ref`)

| Annotator | Gold claims found | Verdict accuracy on found | Contradictions caught |
|---|---|---|---|
| synthetic-b | 21/22 | 90% | 4/6 |

## Adjudication queue

| Item | Claim | ref | synthetic-b |
|---|---|---|---|
| fact-002 | It has 25 free parking spaces. | contradicted | supported |
| fact-003 | Kelotrin is expected to be approved next year. | not_in_sources | opinion |
| fact-006 | beating its 50% target | contradicted | (not extracted) |

## Findings

| Where | Code | Kind | Annotator | Item | Message |
|---|---|---|---|---|---|
| examples/synthetic/fact-annotator-b.jsonl:4 | E307 | error | synthetic-b | fact-004 | evidence quote does not occur verbatim in the cited source: claim 3 'builds autonomous robots that inspect wind turbine': 'The company builds robots that inspect turbine blades.' not in S1 |

## How to read this

- Every evidence quote was checked to occur verbatim in its cited source; paraphrased or invented evidence is an error.
- 'Gold claims found' measures decomposition: a contradiction the annotator never extracted is a missed error, the costliest mistake in factuality data.
- Claims are matched across annotators by span overlap (>= 50%), so annotators may split sentences differently.
