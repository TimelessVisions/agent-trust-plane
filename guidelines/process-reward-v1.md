# Process-reward (step-level reasoning) annotation: guidelines v1

**Task:** you see a problem and a model's step-by-step solution. Label each step `good`, `neutral` or `bad`, **up to and including the first bad step**. Record that step as `first_error_step` with an `error_type`, and say whether the final answer is correct.

These labels train **process reward models (PRMs)**, which score reasoning step by step instead of only checking the final answer. That difference is the point of this task. A solution can reach the right answer through broken steps; an outcome-only grader rewards it, a process grader must not.

**How you are checked** (`annoqa step-check`):
- every arithmetic step carries `calc` and `claims`, and the tool re-evaluates it **exactly** with fractions, not floating point;
- the final answer is compared with the known answer;
- setup, misread and logic errors compute correctly, so arithmetic cannot reveal them. Your first error and error type are scored against **hidden ground truth** for those.

---

## 1. Step labels

| Label | Meaning (PRM800K-style +1 / 0 / -1) |
|---|---|
| `good` | Correct, and it moves the solution forward. |
| `neutral` | Correct but adds nothing: restating the problem or the result, or an unneeded aside. |
| `bad` | Wrong: a false calculation, a misread fact, an invalid inference or a wrong setup. Also any step that is "true" but presented as justified when it is not. |

**First-error convention.** Stop at the first `bad` step. Later steps inherit the error, even when their arithmetic is right, so labelling them adds noise (warning W621). Label every step before the first error (W622 if you skip some on an error-free solution).

## 2. Error types (for the first error)

| Type | Example from the demo set |
|---|---|
| `arithmetic` | "3 x 1.75 = 5.75" (it is 5.25). |
| `misread` | Uses a fact the problem does not state: "the perimeter is length plus width". |
| `setup` | Builds the wrong plan or equation from correctly read facts: "a delay shortens the journey, so subtract 25 min". |
| `logic` | An invalid inference or unjustified leap: "25% off and 10% tax net to 15% off"; "the new score is just 2 above the new average". |

If a step has two problems, choose the type that explains why the step is wrong in the first place: misreading the problem comes before botching its arithmetic.

## 3. The "lucky" solution

In `ps-03`, 4 x 3.50 is written as 15 and 3 x 1.75 as 4.25. The two errors cancel and the change, $0.75, is right. Label it:
- `final_answer_correct: true`, because the answer is right;
- `first_error_step: 1`, `error_type: arithmetic`, because the process is wrong.

A rater who calls this solution correct teaches a model that broken reasoning is fine whenever the answer happens to land. That failure is what process supervision exists to stop.

## 4. Workflow

1. Solve the problem yourself first, or at least know the answer, before you read the solution.
2. Read each step and **verify it independently**: recompute every number, and check every "so" and "therefore".
3. Stop at the first bad step. Write *why* it is bad and what the correct step would be.
4. Check the final answer separately from the process.
5. Run `annoqa step-check`.

## 5. Label format

```json
{"solution_id": "ps-05", "annotator": "you", "step_labels": ["good", "bad"], "first_error_step": 2,
 "error_type": "setup", "final_answer_correct": false,
 "rationale": "Step 2 subtracts the delay as if it shortened the trip; a delay adds time. 155 - 25 = 130 is right arithmetic on a wrong setup."}
```

## Changelog

- **v1**: initial version.
