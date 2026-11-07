# Owner preregistration review — AgentDojo benchmark task annotations

**Status:** REVIEW REQUIRED; no preregistration tag is authorized or created by this report. Source of truth: `bench/ANNOTATION_RULE.md` and the four YAML files. This summary is a preparatory overview, not approval and not an independent annotation audit.

| Suite | `status: ok` | `not_applicable` | Source |
|---|---:|---:|---|
| Workspace | 40 | 0 | [workspace.yaml](workspace.yaml) |
| Travel | 20 | 0 | [travel.yaml](travel.yaml) |
| Banking | 16 | 0 | [banking.yaml](banking.yaml) |
| Slack | 21 | 0 | [slack.yaml](slack.yaml) |
| **Total** | **97** | **0** | |

The derivation rule allows **only** user prompts and pre-injection environment data. It forbids injection text, injection goals, ground-truth tool calls and earlier attack results. Every competitor policy must be generated from the *same* reviewed annotation, recording constraints that a product cannot express with versioned documentation.

## Review before tag approval

- Inspect every capability, scope, resource argument and rule; reject any constraint lacking support in the user request or pre-injection state.
- Review [CHANGES-AFTER-UTILITY.md](CHANGES-AFTER-UTILITY.md). Five first-pass utility fixes are documented: banking tasks 5, 11 and 9; slack task 9; travel task 11. The follow-on annotation additions/re-scoping are described there.
- **Specific travel judgment:** `travel/user_task_11` added a *read-only address lookup* based on an inferred workflow step. The change audit expressly acknowledges that the prompt did not ask for an address. The owner must decide whether this meets the published annotation rule; do not silently rewrite or remove it for better results.
- Confirm there are no hidden task exclusions: all 97 current YAML records show `status: ok`. The benchmark runner separately reports injection tasks with no state-changing ground truth as NOT_APPLICABLE.
- Confirm publication wording is honest: some *development* utility and incident tests ran before the future `bench-annotations-v1` tag. Never claim total blindness to the corpus. The crucial requirement is **no post-tag policy-tuning** for the public comparative sweep.
- Record a review ruling in the SDD ledger before any owner-created tag. If an annotation must change, record the rationale and rerun its utility tests first; only then may the owner choose the frozen commit.

## Tag authorization (owner only)

When satisfied, the owner may specifically approve creation of `bench-annotations-v1` on the reviewed commit. Agents must not create this tag. Only after the owner gate can A1/A2/D5 produce and cite the preregistered headline benchmark results.

**No attack success-rate numbers are claimed in this review.**
