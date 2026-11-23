# Process-reward report

- Solutions: 11; labels read: 22; usable: 22
- Annotators: ref, synthetic-b

## Ground truth

| Solution | Final answer | Known | Final correct | First arithmetic error (computed) | First error (truth) | Type | Outcome vs process |
|---|---|---|---|---|---|---|---|
| ps-01 | 0.75 | 0.75 | yes | - | - | - |  |
| ps-02 | 0.25 | 0.75 | no | 2 | 2 | arithmetic |  |
| ps-03 | 0.75 | 0.75 | yes | 1 | 1 | arithmetic | **lucky: right answer, wrong process** |
| ps-04 | 12:40 | 12:40 | yes | - | - | - |  |
| ps-05 | 11:50 | 12:40 | no | - | 2 | setup |  |
| ps-06 | 34 | 33 | no | - | 1 | logic |  |
| ps-07 | 33 | 33 | yes | - | - | - |  |
| ps-08 | 50 | 50 | yes | - | - | - |  |
| ps-09 | 200 | 50 | no | - | 2 | misread |  |
| ps-10 | 90 | 90 | yes | - | - | - |  |
| ps-11 | 84 | 90 | no | - | 2 | logic |  |

## Annotator accuracy

| Annotator | n | First error exact | Error type (when step right) | Final-answer accuracy | Arithmetic errors missed |
|---|---|---|---|---|---|
| ref | 11 | 11/11 | 6/6 | 11/11 | 0 |
| synthetic-b | 11 | 9/11 | 3/4 | 11/11 | 2 |

## Agreement

| Pair | Same first error | Step-label alpha (nominal, labelled steps) |
|---|---|---|
| ref / synthetic-b | 9/11 | 0.871 |

## Findings

| Where | Code | Kind | Annotator | Solution | Message |
|---|---|---|---|---|---|
| examples/synthetic/process-annotator-b.jsonl:3 | V611 | mismatch | synthetic-b | ps-03 | a step labelled good/neutral has arithmetic that does not check out: step 1: 4*3.50 = 14, not 15 |
| examples/synthetic/process-annotator-b.jsonl:3 | V611 | mismatch | synthetic-b | ps-03 | a step labelled good/neutral has arithmetic that does not check out: step 2: 3*1.75 = 5.25, not 4.25 |
| examples/synthetic/process-annotator-b.jsonl:3 | V614 | mismatch | synthetic-b | ps-03 | first error differs from ground truth: labelled None, ground truth 1 |
| examples/synthetic/process-annotator-b.jsonl:5 | V614 | mismatch | synthetic-b | ps-05 | first error differs from ground truth: labelled 4, ground truth 2 |
| examples/synthetic/process-annotator-b.jsonl:9 | V615 | mismatch | synthetic-b | ps-09 | error type differs from ground truth: labelled setup, ground truth misread |

## How to read this

- An **outcome** reward only checks the final answer; a **process** reward checks every step. A 'lucky' solution (right answer, wrong steps) gets full outcome reward, and a rater who labels it correct teaches a model that broken reasoning is fine.
- Arithmetic is re-checked exactly (fractions, no floating point). Setup, misread and logic errors compute correctly, so only a careful human finds them; they are scored against hidden ground truth.
