# Code evaluation: guidelines v1

**Task:** you see a programming task and one AI-written solution, sometimes with the AI's own explanation of it. Decide whether the code is **correct**, score it on six dimensions, list concrete issues, and, if you say it is incorrect, give a **failing input**: a call that shows the bug.

What makes this rubric different: your verdict is **checked by execution**. `annoqa code-check` runs the solution against hidden tests, and runs your failing input against a trusted reference implementation. A verdict without evidence is not accepted, and evidence that does not reproduce is reported.

---

## 1. Workflow per item

1. Read the **task** and list its requirements, including the implicit ones: return type, empty input, duplicates, error behaviour, input size.
2. Read the code line by line. Do not skim because it "looks standard": most bugs in AI code sit in code that looks standard.
3. **Trace it by hand** on one normal input and on every edge input you listed in step 1. Write down what it returns.
4. If you find a bug, reduce it to the **smallest failing input** you can, and record it as `failing_input`: the list of call arguments.
5. Check the AI's **explanation** against the code. An explanation that claims something the code does not do is its own issue.
6. Score, list issues, choose the verdict, and write the rationale (sections 2–5).
7. Run `annoqa code-check`. Fix every error, and reread any item marked as a mismatch.

## 2. Verdict

- **incorrect**: there is at least one input that the task allows on which the code returns the wrong value, raises when it should not, fails to raise when the task says to, never terminates, or is unsafe. You **must** give a `failing_input` (check V305).
- **correct**: you looked for such an input, including every edge case in step 1, and found none.

Performance and style problems alone do not make code incorrect. They lower the scores (section 3). The one exception: if the task states a size or time bound and the code clearly cannot meet it, say so as a `performance` issue at severity `major` or `blocker`. You may still choose `correct` if the logic is right; explain your choice.

## 3. Dimensions (1–5)

| Dimension | 5 | 3 | 1 |
|---|---|---|---|
| `correctness` | Right on every allowed input you could find | Right on typical inputs, wrong on a plausible one | Wrong on typical inputs, or does not run |
| `edge_cases` | Empty, single, duplicate, boundary and invalid inputs all handled as specified | Some edge cases mishandled | Edge cases ignored |
| `efficiency` | Meets the stated or expected complexity | Works but is noticeably slower than needed | Unusable at the stated input size |
| `security` | No injection, traversal, unsafe eval or secret exposure | A weakness that needs care to exploit | Directly exploitable (e.g. path traversal on user input) |
| `readability` | Clear names and structure; easy to review | Understandable with effort | Hard to follow or misleading |
| `explanation_accuracy` | The explanation matches what the code does | Partly accurate or vague | Claims behaviour the code does not have |

Score each dimension on its own. A correct but O(n²) solution can be `correctness 5, efficiency 2`. If the task does not touch security at all, `security` is 5 unless the code adds a risk of its own.

Consistency checks: `incorrect` with correctness 4–5 (W401); `correct` with correctness 1–2 (W402); a `security` issue with security 4–5 (W403); a `blocker` issue on a `correct` verdict (W404).

## 4. Issues

List each problem as `{category, severity, description}`.

| Category | Meaning |
|---|---|
| `logic_bug` | Wrong result on normal inputs |
| `edge_case` | Wrong result on empty, single, duplicate or boundary inputs |
| `spec_mismatch` | Solves a different problem than the one asked (wrong ordering rule, wrong return shape) |
| `security` | Injection, traversal, unsafe deserialisation or eval, secret leakage |
| `performance` | Complexity or resource use unsuitable for the stated inputs |
| `error_handling` | Missing, wrong or swallowed exceptions compared with the spec |
| `explanation_mismatch` | The explanation misdescribes the code |
| `style` | Readability only; never the sole reason for `incorrect` |

| Severity | Meaning |
|---|---|
| `blocker` | Makes the solution unusable or unsafe for its stated purpose |
| `major` | Wrong on realistic inputs, but fixable in a few lines |
| `minor` | Cosmetic, or wrong only in a contrived case |

The description must say *what* is wrong and *where*: "line 3 `while lo < hi` exits before checking the last index", not "off-by-one".

## 5. Rationale

At least 15 words. State the verdict, the decisive evidence (the failing input and what the code returns versus what it should return), and the strongest point of the code if it is correct. Write it for a reviewer who will not rerun anything.

> **Good:** "Incorrect. With arr=[1, 3, 5, 7] and target 7 the loop `while lo < hi` stops when lo == hi == 3 without comparing arr[3], so it returns -1 instead of 3. It needs `<=`. The explanation calls it 'standard binary search', which hides the bug."

## 6. Edge cases for annotators

| Situation | Rule |
|---|---|
| The code is right but the explanation is wrong | Verdict `correct`; `explanation_mismatch` issue; lower `explanation_accuracy`. |
| The code is wrong only for inputs the task rules out | Not a bug. Say which assumption you relied on. |
| You cannot decide what the spec intends | Choose the most reasonable reading, say which one in the rationale, and do not mark the other reading as a bug. |
| The tests pass but you found a real failing input | Keep `incorrect` and give the input. If the reference confirms it, the report credits it as a **test gap you found**. |
| Your failing input is not confirmed (V303) | Re-trace it. Either your input is wrong or the reference disagrees with your reading of the spec; explain which in the rationale. |
| The code has a security hole the task did not ask about | Still a `security` issue; if user input reaches it, it is at least `major`. |

## Changelog

- **v1**: initial version.
