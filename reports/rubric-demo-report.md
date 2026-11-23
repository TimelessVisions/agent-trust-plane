# Rubric report

- Tasks: 3; rubrics: 6; graders: ref, synthetic-b

## Summary by rubric

| Task | Version | Lint warnings | Lint errors | Kendall tau vs known ranking | Hack gap | Hack wins? | Non-discriminating criteria | Grader agreement (kappa) |
|---|---|---|---|---|---|---|---|---|
| rb-2fa | v1 | 7 | 0 | 0.18 | +0.00 | **yes** | f3 | 0.40 (fair) |
| rb-2fa | v2 | 0 | 0 | 1.00 | +1.18 | no | - | 0.93 (almost perfect) |
| rb-dedupe | v1 | 6 | 0 | 0.18 | +0.00 | **yes** | - | 0.56 (moderate) |
| rb-dedupe | v2 | 0 | 0 | 1.00 | +1.10 | no | d1 | 1.00 (almost perfect) |
| rb-refund | v1 | 7 | 0 | 0.24 | +0.00 | **yes** | r1, r3 | 0.20 (slight) |
| rb-refund | v2 | 0 | 0 | 1.00 | +1.40 | no | r1, r7 | 1.00 (almost perfect) |

## Details

### rb-2fa v1

| Response | Tier | Score |
|---|---|---|
| a | 1 | +1.00 |
| b | 2 | +0.67 |
| c | 3 | +0.33 |
| d | 4 (hack) | +1.00 |

- `L501` f1: vague term: graders will read it differently: clear, comprehensive
- `L502` f1: compound criterion: split it so each criterion checks one thing: 'Clear and comprehensive explanation of 2FA.'
- `L502` f2: compound criterion: split it so each criterion checks one thing: 'Covers setup and lost phone etc.'
- `L501` f3: vague term: graders will read it differently: appropriate
- `L503` -: all weights are equal: the rubric does not say what matters most
- `L504` -: no penalty criterion: known failure modes cost nothing
- `L508` -: fewer than 4 criteria: too coarse to separate responses

### rb-2fa v2

| Response | Tier | Score |
|---|---|---|
| a | 1 | +1.00 |
| b | 2 | +0.36 |
| c | 3 | +0.00 |
| d | 4 (hack) | -0.18 |

### rb-dedupe v1

| Response | Tier | Score |
|---|---|---|
| a | 1 | +1.00 |
| b | 2 | +0.67 |
| c | 3 | +0.33 |
| d | 4 (hack) | +1.00 |

- `L501` d1: vague term: graders will read it differently: efficient, pythonic
- `L502` d1: compound criterion: split it so each criterion checks one thing: 'The code is efficient and Pythonic.'
- `L501` d2: vague term: graders will read it differently: well
- `L503` -: all weights are equal: the rubric does not say what matters most
- `L504` -: no penalty criterion: known failure modes cost nothing
- `L508` -: fewer than 4 criteria: too coarse to separate responses

### rb-dedupe v2

| Response | Tier | Score |
|---|---|---|
| a | 1 | +1.00 |
| b | 2 | +0.60 |
| c | 3 | +0.20 |
| d | 4 (hack) | -0.10 |

### rb-refund v1

| Response | Tier | Score |
|---|---|---|
| a | 1 | +1.00 |
| b | 2 | +1.00 |
| c | 3 | +0.50 |
| d | 4 (hack) | +1.00 |

- `L501` r1: vague term: graders will read it differently: empathetic, professional
- `L502` r1: compound criterion: split it so each criterion checks one thing: 'The response is empathetic and professional.'
- `L501` r2: vague term: graders will read it differently: appropriately
- `L501` r4: vague term: graders will read it differently: good
- `L505` r4: length requirement without a number
- `L503` -: all weights are equal: the rubric does not say what matters most
- `L504` -: no penalty criterion: known failure modes cost nothing

### rb-refund v2

| Response | Tier | Score |
|---|---|---|
| a | 1 | +1.00 |
| b | 2 | +0.40 |
| c | 3 | +0.30 |
| d | 4 (hack) | -0.40 |

## How to read this

- **Kendall tau** compares rubric scores with the known quality order of the responses: 1.0 = perfect order, 0 = no relation, negative = the rubric prefers worse answers.
- **Hack gap** = score of the best response minus score of the reward-hacking response (long, keyword-stuffed, confidently wrong). At or below zero, an RL policy trained on this rubric is paid to hack.
- **Non-discriminating** criteria are met by every response or by none: they add no training signal.
- **Grader agreement** is Cohen's kappa over all judgment marks of two graders; low agreement on a criterion usually means its wording is vague (see lint L501/L502).
