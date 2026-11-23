# Factuality and source checking: guidelines v1

**Task:** you see a question, one or more **source documents** and an AI **response** that should be based on them. Split the response into atomic claims, judge each claim against the sources, and back every judgment with a **verbatim quote**.

This is grounding / faithfulness annotation, as used for retrieval-augmented (RAG) systems and summarisation. The sources are the only ground truth: you judge whether a claim follows from the sources, not whether it is true in the outside world.

`annoqa fact-check` verifies what can be checked mechanically:
- every claim is a verbatim span of the response;
- every quote occurs verbatim in the source it cites;
- every number in a supported claim appears in its evidence;
- together, the claims cover the response.

---

## 1. Workflow per item

1. Read the question, then **all** sources. Note each source's date and kind (current page, archive, press release). Sources can disagree.
2. Read the response once without judging it.
3. **Decompose** it into claims (section 2). Copy each claim's text exactly from the response.
4. Give each claim a verdict (section 3). For `supported` and `contradicted`, copy the evidence exactly from the source and record its source id.
5. For each `contradicted` claim, write a one-line **correction** that states what the source says.
6. Write a short rationale for the item: the key errors, and any judgment call you made.
7. Run `annoqa fact-check`. Fix every error, and look at every warning.

## 2. Decomposing into claims

A **claim** is the smallest part of the response that can be true or false on its own.

- Split a sentence that makes several checkable statements. "Founded in 2019 by Raman and Lindqvist in Stockholm" holds two claims, the founding and the location, because one can be right while the other is wrong.
- Keep a statement together when splitting it would lose meaning. "Up from 41% the year before" is one claim.
- **Evaluative conclusions are claims too.** "Beating its 50% target" is checkable against the numbers even though it sounds like commentary. Missing such claims is the most common decomposition error.
- Every sentence of the response must be touched by at least one claim. Pure opinion still gets a claim, with verdict `opinion` (warning W311 fires below 80% coverage).
- Claims must not duplicate each other (W313).

## 3. Verdicts

| Verdict | Use when | Evidence |
|---|---|---|
| `supported` | The sources state it, or it follows directly from what they state. A faithful paraphrase counts. | Required: the quote(s) that support it. |
| `contradicted` | The sources state something incompatible with it: a wrong number, a wrong entity, an inverted conclusion, or a claim the source rules out. | Required: the quote that contradicts it, plus a `correction`. |
| `not_in_sources` | Checkable, but the sources neither support nor contradict it. Added detail, guesses and forecasts go here. | None (W314 if given). |
| `opinion` | A value judgment that cannot be checked ("a sensible compromise"). | None. |

Decision rules:
- **Numbers must match exactly**, after allowing formatting such as 1,000 = 1000. "$4.2 million" against a source saying "$2.4 million" is `contradicted`, not "roughly right". If a supported claim has a number that its evidence lacks, W312 fires.
- **Paraphrase is fine; changing meaning is not.** "Doubles from 500 to 1,000" is supported by "changes from 500 to 1,000". "Chairs the finance committee" is contradicted by "chairs the transport committee".
- **When sources conflict, the more recent or more authoritative source wins**, and you cite it. A claim taken from an archived page that a current page updates is `contradicted`. Say so in the correction.
- **Claims the source explicitly rules out are `contradicted`, not `not_in_sources`.** "The trial showed it reduces heart attacks" is contradicted by "the trial was not designed to measure effects on heart attacks".
- **Watch who said what.** If the source attributes a statement to supporters, a response attributing it to "critics of the delay" can still be right: supporters of a bike lane are critics of delaying it. Read carefully before marking an attribution as wrong.
- A forecast or prediction that the sources do not make is `not_in_sources`, even when it is phrased as fact ("is expected to be approved next year"). Use `opinion` only for value judgments.

## 4. Evidence

- Copy quotes **exactly**: same words, same order. Only whitespace and curly versus straight quotes are normalised. A paraphrased "quote" is rejected (E307), because a reviewer must be able to find it with Ctrl+F.
- Quote the shortest passage that settles the claim. One sentence is usually enough.
- Cite the source id the quote comes from (E306 if the id is wrong).

## 5. Rationale

At least one sentence per contradicted claim, plus any judgment call (conflicting sources, attribution, forecast or opinion). Example:

> "Two contradictions: the cost figure has its digits swapped ($4.2m vs $2.4m) and Ortiz chairs the transport, not finance, committee. The $300,000 warning came from supporters of the lane, i.e. critics of the delay, so that claim holds."

## 6. Quality signals in the report

- **Factual precision** of a response = supported / (supported + contradicted + not_in_sources). Opinions are excluded.
- **Gold claims found** = how many reference claims you also extracted (matched by span overlap of 50% or more).
- **Contradictions caught**: the number the reviewer cares most about. An error you never extracted is an error that ships.

## Changelog

- **v1**: initial version.
