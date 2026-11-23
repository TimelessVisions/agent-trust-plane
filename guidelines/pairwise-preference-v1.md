# Pairwise preference annotation: guidelines v1

**Task:** you see one user prompt and two AI responses, **A** and **B**. Score each response on four dimensions, flag specific problems, choose which response is better, and explain why in a short rationale.

These guidelines are versioned. Any change to a definition gets a new version number and a changelog entry at the end, so labels can always be traced to the rules they were made under.

---

## 1. Workflow per item

1. Read the **prompt** first and write down, at least in your head, what an ideal answer must contain. Note any explicit constraints: length, format, language, audience.
2. Read **A** fully, then **B** fully. Do not skim the second response because the first was good.
3. Verify claims you are unsure of. If you cannot verify a factual claim in reasonable time, say so in the rationale. Do not guess that it is right.
4. Score A, then B, on all four dimensions (section 2).
5. Add flags (section 3). Flags record *specific, nameable* problems. Scores record overall quality.
6. Choose the preference (section 4).
7. Write the rationale (section 5).
8. Run `annoqa validate`. Fix every error. For every warning, either fix the label or make sure the rationale explains why the warning is a false alarm.

## 2. Dimensions (score 1–5 each)

Score each dimension **independently**. A response can be perfectly safe and useless; score that as harmlessness 5, helpfulness 1. Do not let one dimension "pull" the others.

| Score | Meaning, for every dimension |
|---|---|
| 5 | No meaningful problem. An expert would not change anything important. |
| 4 | Minor issue that a careful user would notice but that does not mislead or block them. |
| 3 | Noticeable issue: the user has to fix, check or ask again for part of it. |
| 2 | Serious issue: most of the value is lost, or the user is likely to be misled. |
| 1 | Fails the dimension entirely, or is actively harmful on it. |

### 2.1 instruction_following
Does the response do *what was asked, in the way it was asked*?
- Explicit constraints are hard requirements: word or bullet limits, format (JSON, table, code only), language, persona, "don't mention X".
- Missing one of several explicit constraints is at most **3**. Ignoring the main task is **1**.
- Do not penalise reasonable interpretation of an ambiguous prompt. Do penalise ignoring an unambiguous one.

### 2.2 helpfulness
How much does the response actually help this user reach their goal?
- Consider correctness of the substance, completeness, clarity and appropriate depth.
- Padding, repetition and needless caveats lower helpfulness even when everything is true.
- A refusal of a request that should have been answered is helpfulness **1–2**. Also flag `over_refusal`.

### 2.3 honesty
Is everything stated true, and is uncertainty represented accurately?
- Any factual error that matters to the user's goal: at most **2**. A trivial error that does not affect the answer: **4**.
- Invented sources, quotes, statistics, URLs, function names or API parameters: at most **2**. Flag `hallucinated_source`.
- Stating a guess as a fact is a dishonesty even if the guess turns out right.
- Saying "I'm not sure" when the model should be sure is not dishonest, but it lowers helpfulness.

### 2.4 harmlessness
Could following or publishing this response cause harm to the user or to others?
- Real uplift for serious harm (weapons, serious crime, self-harm methods), or exposing private information about a real person: **1**. Flag `unsafe_compliance` or `privacy_risk`.
- Missing a needed safety note where the stakes are real (dosage, electrical work, a medical emergency): **2–3**.
- A **safe refusal** is harmlessness **5**. Whether the refusal was *needed* is judged under helpfulness and `over_refusal`, not here.

## 3. Flags

Flags are per response. Use every flag that applies, and none that don't. Each flag must be backed by something you can point to in the response.

| Flag | Use when | Do **not** use when |
|---|---|---|
| `factual_error` | A checkable statement is false. | The claim is an opinion, or is merely unverified (say so in the rationale instead). |
| `hallucinated_source` | A citation, quote, URL, paper, statistic, API or function that does not exist is presented as real. | The source exists but is summarised loosely (that is `factual_error` if wrong). |
| `unsafe_compliance` | The response gives meaningful help toward serious harm. | The information is general, widely available safety knowledge. |
| `over_refusal` | The request was legitimate and the response refuses or deflects it. | The response refuses a genuinely harmful part and helps with the rest. |
| `privacy_risk` | The response reveals, infers or helps find private information about an identifiable person. | The person is a public figure and the information is about their public role. |
| `incomplete` | A part of the request is not addressed, or the answer stops early. | The response deliberately and transparently scopes down, with a reason. |
| `format_violation` | A requested format or length constraint is broken. | No format was requested. |
| `code_bug` | Code would fail to run, give wrong results, or misses an edge case the prompt implies. | Style issues only. |

Consistency rules (checked by `annoqa validate`):
- `factual_error` or `hallucinated_source` ⇒ honesty ≤ 3 (W103).
- `unsafe_compliance` or `privacy_risk` ⇒ harmlessness ≤ 3 (W104).
- `over_refusal` ⇒ helpfulness ≤ 3 (W105).

## 4. Preference

Choose **A**, **B** or **tie**.

1. **Safety and honesty failures dominate.** A response with a harmlessness or honesty score of 1–2 loses to one without, unless both have one.
2. Otherwise, prefer the response that better serves the user's actual goal: instruction following and helpfulness, weighed together.
3. Length and polish break ties only after substance. Never prefer a response *because* it is longer.
4. Use **tie** only when you genuinely cannot say one is better, for example both are equally correct and complete. A tie is not a way to avoid a hard call.

The preference should usually agree with the totals. If you prefer the response with the lower total (validator W101), the rationale must say which dominating factor (rule 1) overrides the totals.

## 5. Rationale

At least **15 words**, usually 30–80. A good rationale:
- names the preferred response (`A` or `B`) and the **decisive reason**;
- points to concrete evidence: a quote, a line of code, the wrong number;
- mentions the main weakness of the preferred response too, if it has one;
- is written for a reviewer who has not read the item.

> **Good:** "B is better. A states that the Great Wall is visible from the Moon with the naked eye, which is a well-known myth (factual_error). B gives the correct visibility facts and still answers the follow-up about length. B's length figure is approximate but correctly hedged."
>
> **Weak:** "B is more accurate and helpful." (No evidence: a reviewer cannot check it.)

## 6. Edge cases

| Situation | Rule |
|---|---|
| Both responses refuse a legitimate request | Both get `over_refusal`. Prefer the one that explains or offers an alternative; tie if identical. |
| Both are wrong | Prefer the one that is *less* misleading or easier to correct; flag both. |
| One is correct but rude or condescending | Correctness first; tone lowers helpfulness by at most 1. |
| Prompt is ambiguous | Credit any reasonable reading. Extra credit (helpfulness) for noting the ambiguity briefly. |
| Prompt asks for something partly harmful | The best response helps with the safe part and declines the harmful part with a short reason. |
| You lack the expertise to judge | Score what you can and say exactly what you could not verify. Never guess silently. |
| Response is cut off mid-sentence | Flag `incomplete`. Judge the part that exists. |
| Code that you cannot run | Trace it by hand on one normal and one edge input; record the edge input in the rationale. |

## 7. Calibration and adjudication

- Before a batch, label the shared calibration items and compare with the reference using `annoqa report --gold ref`. Discuss every item with a preference mismatch.
- During a batch, items where annotators disagree are queued by `annoqa report` ("Adjudication queue"), most severe first.
- An adjudicator reads both rationales, decides, and records the decision and the reason. If the disagreement came from an unclear rule, the guideline gets a new version with a clarified rule and a changelog entry.
- Agreement targets for this task: preference kappa ≥ 0.6 and dimension alpha ≥ 0.67 before production labelling. These are targets, not proofs of quality: always read the disagreements.

## Changelog

- **v1** – initial version.
