# Rubric authoring for rubric-based rewards: guidelines v1

**Task:** for a prompt, write the rubric a grader (human or LLM judge) will use to score responses. In RL with rubric rewards, **the rubric is the reward function**. Every vague word becomes noise in the reward. Every missing penalty becomes a behaviour the policy is paid to learn.

`annoqa rubric-eval` holds a rubric to four tests:

| Test | Question | Measured by |
|---|---|---|
| Well-formed | Is each criterion atomic, specific, weighted, and observable? | lint rules L500–L509 |
| Valid | Do scores rank responses in their known quality order? | Kendall's tau against the known tiers |
| Hack-resistant | Does a long, keyword-stuffed, confidently wrong response score low? | hack gap (best minus hack) |
| Reliable | Do two graders mark each criterion the same way? | Cohen's kappa over judgment marks |

---

## 1. Writing criteria

1. **One check per criterion.** "Empathetic and professional" is two criteria, and graders will disagree on which half counts (L502). Split it.
2. **Observable, not evaluative.** Replace "handles the refund appropriately" with what an expert would *see*: "States that the order is eligible because it is within the 30-day window" and "Asks the customer to send a photo of the damage". Words like *good, clear, appropriate, comprehensive, efficient* are flagged by L501.
3. **Numbers instead of adjectives.** Write "at most 120 words", not "good length" (L505).
4. **Weight by importance.** Policy-critical facts get weight 3, helpful extras 1. Equal weights everywhere (L503) say nothing about what matters.
5. **Penalties for the known failure modes.** Every task has predictable ways to go wrong: promising a refund before the photo arrives, `list(set(x))` destroying order, "just disable 2FA". Give each a negative weight and start its text with `PENALTY:` (L504, L509).
6. **Machine checks where possible.** If a criterion can be checked by string inclusion, a word limit or a regex, make it `kind: verifiable` with a `check`. That part of the reward then has no grader noise, as in RL with verifiable rewards. A verifiable criterion without a valid check is an error (L506).
7. **No double counting.** Two criteria that reward the same thing inflate it (L507).
8. **Enough resolution.** Fewer than four criteria cannot separate a good answer from a merely plausible one (L508).

## 2. Testing a rubric before it ships

1. Collect 4+ responses whose quality order you know: an expert answer, a good-but-incomplete one, a generic one, and a **reward hack**. The hack is long, confident, stuffed with the rubric's own keywords, and wrong.
2. Grade them with the rubric. Then check the following:
   - **tau** should be close to 1.0. A rubric that scores the generic answer above the incomplete one has the wrong priorities.
   - **The hack gap must be clearly positive.** If the hack ties or wins, the rubric rewards surface features. In the demo, every v1 rubric loses to the hack; every v2 rubric beats it by more than one full point.
   - **Non-discriminating criteria** (met by all responses, or by none) add no signal on this set. Keep them only if they guard against a failure that these responses happen not to show, and say so.
3. Have a second person grade the same responses. Rewrite any criterion they mark differently: low agreement is almost always a wording problem.
4. **Do not tune the rubric to this one set of responses.** Hold some responses back, or write new ones after revising.

## 3. Format

```json
{"task_id": "rb-refund", "version": "v2", "criteria": [
  {"id": "r2", "text": "States that the order is eligible because it is within the 30-day window.", "weight": 3, "kind": "judgment"},
  {"id": "r3", "text": "Asks the customer to send a photo of the damage.", "weight": 3, "kind": "verifiable",
   "check": {"includes_any": ["photo", "picture", "image"]}},
  {"id": "r5", "text": "PENALTY: promises or issues the refund before the photo is received.", "weight": -3, "kind": "judgment"}
]}
```

Check types: `includes_any` (a list of case-insensitive substrings), `max_words` (an integer) and `regex`. A criterion is *met* when its condition holds. For a penalty, "met" means the failure is present, so its negative weight applies.

**Score** = the sum of the weights of met criteria divided by the maximum possible positive total. 1.0 means every reward criterion is met and no penalty applies; negative scores are possible.

## Changelog

- **v1**: initial version.
