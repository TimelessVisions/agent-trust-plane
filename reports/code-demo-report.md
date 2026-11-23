# Code-evaluation report

- Code items: 10; labels read: 20; usable: 20
- Annotators: ref, synthetic-b

## Hidden test results (ground truth)

| Item | Function | Tests passed | Verdict from tests | First failure |
|---|---|---|---|---|
| code-001 | `second_largest` | 1/5 | incorrect | [[5, 5, 3]] -> expected 3, got 5 |
| code-002 | `is_palindrome` | 3/4 | incorrect | ["A man, a plan, a canal: Panama"] -> expected True, got False |
| code-003 | `merge_intervals` | 3/4 | incorrect | [[[8, 10], [1, 3], [2, 6]]] -> expected [[1, 6], [8, 10]], got [[8, 10]] |
| code-004 | `parse_duration` | 6/6 | correct | - |
| code-005 | `binary_search` | 3/5 | incorrect | [[1, 3, 5, 7], 7] -> expected 3, got -1 |
| code-006 | `top_words` | 2/3 | incorrect | ["pear apple pear apple fig", 2] -> expected [['apple', 2], ['pear', 2]], got [['pear', 2], ['apple', 2]] |
| code-007 | `safe_join` | 2/4 | incorrect | ["/srv/files", "../secret"] -> expected ValueError, got return value '/srv/files/../secret' |
| code-008 | `chunk` | 4/4 | incorrect (confirmed by an annotator's failing input) | - |
| code-009 | `two_sum` | 3/3 | correct | - |
| code-010 | `moving_average` | 2/4 | incorrect | [[1, 2, 3, 4], 2] -> expected [1.5, 2.5, 3.5], got [1.5, 2.5] |

## Annotator accuracy

| Annotator | n | Verdict accuracy | Missed bugs | False alarms | Failing inputs confirmed |
|---|---|---|---|---|---|
| ref | 10 | 100% | 0 | 0 | 8/8 |
| synthetic-b | 10 | 80% | 2 | 0 | 5/6 |

## Agreement

| Field | Krippendorff's alpha | Level | Reading |
|---|---|---|---|
| verdict | 0.548 | nominal | unreliable |
| correctness | 0.819 | ordinal | reliable |
| edge_cases | 0.743 | ordinal | tentative |
| efficiency | 0.998 | ordinal | reliable |
| security | 1.000 | ordinal | reliable |
| readability | 0.900 | ordinal | reliable |
| explanation_accuracy | 0.632 | ordinal | unreliable |

| Pair | n | Verdict % agree | Verdict kappa |
|---|---|---|---|
| ref / synthetic-b | 10 | 80% | 0.545 (moderate) |

## Score error against `ref`

| Annotator | correctness | edge_cases | efficiency | security | readability | explanation_accuracy |
|---|---|---|---|---|---|---|
| synthetic-b | 0.50 | 0.50 | 0.10 | 0.00 | 0.10 | 0.60 |

## Findings

| Where | Code | Kind | Annotator | Item | Message |
|---|---|---|---|---|---|
| examples/synthetic/code-annotator-b.jsonl:3 | V303 | mismatch | synthetic-b | code-003 | the failing input does not expose a bug: candidate and reference agree: [[[1, 3], [2, 6], [8, 10]]]: both give [[1, 6], [8, 10]] |
| examples/synthetic/code-annotator-b.jsonl:5 | V301 | mismatch | synthetic-b | code-005 | verdict 'correct', but hidden tests fail: [[1, 3, 5, 7], 7] -> expected 3, got -1 |
| examples/synthetic/code-annotator-b.jsonl:8 | V306 | mismatch | synthetic-b | code-008 | verdict 'correct', but another annotator's confirmed failing input exposes a bug: from ref, candidate and reference disagree: [[1, 2], -1]: candidate gives [], reference gives raises ValueError |
| data/code/labels/reference.jsonl:1 | V304 | confirmed | ref | code-001 | failing input confirmed: candidate and reference disagree: [[5, 5, 3]]: candidate gives 5, reference gives 3 |
| examples/synthetic/code-annotator-b.jsonl:1 | V304 | confirmed | synthetic-b | code-001 | failing input confirmed: candidate and reference disagree: [[5, 5, 3]]: candidate gives 5, reference gives 3 |
| data/code/labels/reference.jsonl:2 | V304 | confirmed | ref | code-002 | failing input confirmed: candidate and reference disagree: ["A man, a plan, a canal: Panama"]: candidate gives False, reference gives True |
| examples/synthetic/code-annotator-b.jsonl:2 | V304 | confirmed | synthetic-b | code-002 | failing input confirmed: candidate and reference disagree: ["A man, a plan, a canal: Panama"]: candidate gives False, reference gives True |
| data/code/labels/reference.jsonl:3 | V304 | confirmed | ref | code-003 | failing input confirmed: candidate and reference disagree: [[[8, 10], [1, 3], [2, 6]]]: candidate gives [[8, 10]], reference gives [[1, 6], [8, 10]] |
| data/code/labels/reference.jsonl:5 | V304 | confirmed | ref | code-005 | failing input confirmed: candidate and reference disagree: [[1, 3, 5, 7], 7]: candidate gives -1, reference gives 3 |
| data/code/labels/reference.jsonl:6 | V304 | confirmed | ref | code-006 | failing input confirmed: candidate and reference disagree: ["pear apple pear apple fig", 2]: candidate gives [['pear', 2], ['apple', 2]], reference gives [['apple', 2], ['pear', 2]] |
| examples/synthetic/code-annotator-b.jsonl:6 | V304 | confirmed | synthetic-b | code-006 | failing input confirmed: candidate and reference disagree: ["pear apple pear apple fig", 2]: candidate gives [['pear', 2], ['apple', 2]], reference gives [['apple', 2], ['pear', 2]] |
| data/code/labels/reference.jsonl:7 | V304 | confirmed | ref | code-007 | failing input confirmed: candidate and reference disagree: ["/srv/files", "../secret"]: candidate gives '/srv/files/../secret', reference gives raises ValueError |
| examples/synthetic/code-annotator-b.jsonl:7 | V304 | confirmed | synthetic-b | code-007 | failing input confirmed: candidate and reference disagree: ["/srv/files", "../secret"]: candidate gives '/srv/files/../secret', reference gives raises ValueError |
| data/code/labels/reference.jsonl:8 | V304 | confirmed | ref | code-008 | failing input confirmed: candidate and reference disagree: [[1, 2], -1]: candidate gives [], reference gives raises ValueError |
| data/code/labels/reference.jsonl:10 | V304 | confirmed | ref | code-010 | failing input confirmed: candidate and reference disagree: [[1, 2, 3, 4], 2]: candidate gives [1.5, 2.5], reference gives [1.5, 2.5, 3.5] |
| examples/synthetic/code-annotator-b.jsonl:10 | V304 | confirmed | synthetic-b | code-010 | failing input confirmed: candidate and reference disagree: [[1, 2, 3, 4], 2]: candidate gives [1.5, 2.5], reference gives [1.5, 2.5, 3.5] |

## How to read this

- Ground truth comes from execution, not opinion: hidden tests, plus any annotator failing input that the trusted reference implementation confirms. A confirmed failing input on an item whose tests pass is a **test gap** the annotator found.
- 'Missed bugs' (verdict correct on a buggy item) are the costliest annotation error for code data.
- Efficiency, security and readability are judged, not tested; compare them with agreement and gold error.
