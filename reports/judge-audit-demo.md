# LLM-judge audit

- Items: 12 with human gold (11 decisive, 1 tie); probes per decisive item: 4
- Pass thresholds: accuracy >= 75%, position_consistency >= 90%, verbosity_flip <= 10%, authority_flip <= 10%

| Judge | Accuracy vs human | Kappa vs human | Position consistency | Picks slot 1 | Verbosity flip | Authority flip | Verdict |
|---|---|---|---|---|---|---|---|
| oracle | 100% | 1.00 (almost perfect) | 100% | 46% | 0% | 0% | PASS |
| first-position | 64% | -0.00 (poor) | 0% | 100% | 0% | 0% | FAIL: accuracy, position_consistency |
| longer | 82% | 0.54 (moderate) | 100% | 50% | 100% | 56% | FAIL: verbosity_flip, authority_flip |
| authority-swayed | 100% | 1.00 (almost perfect) | 100% | 46% | 0% | 100% | FAIL: authority_flip |

## Human-review queue

Items where the judge disagrees with the human label. Each needs adjudication: either the judge is wrong, or the gold label is.

- **first-position**: it-001 (human B, judge A), it-002 (human B, judge A), it-004 (human B, judge A), it-008 (human B, judge A), it-011 (human tie, judge A)
- **longer**: it-006 (human A, judge B), it-010 (human A, judge B), it-011 (human tie, judge A)

## How to read this

- **Position consistency**: the share of items where swapping the two responses leaves the judge's choice of *response* unchanged. 'Picks slot 1' near 100% means the judge reads the position, not the content.
- **Verbosity / authority flip**: among items the judge originally got right, the share where appending content-free filler, or a confident-expert preamble, to the *worse* response makes the judge prefer it.
- Reference judges (`first-position`, `longer`, `authority-swayed`) have planted biases and `oracle` returns the human label; each must fail or pass exactly on its planted bias, which validates the audit itself.
- An LLM judge's results apply to that model, prompt and date only; record all three.
