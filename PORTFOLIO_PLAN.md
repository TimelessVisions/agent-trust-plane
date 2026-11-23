# Portfolio plan: frontier human-data work for 2027

## Goal

By early 2027, have one public portfolio that shows, with runnable evidence, that its author can do the human-data work frontier AI labs pay the most for. That work is no longer "label 10,000 images". It is:

1. **judging what agents do**, step by step, in tool-using environments;
2. **writing rubrics** that become reward signals for RL;
3. **labelling reasoning at the step level** (process rewards, first-error location);
4. **auditing LLM judges** against human gold;
5. **red-teaming**, with a precise harm taxonomy;

all with measured quality: agreement, gold accuracy and adjudication.

**The one-line pitch:** *every label in this portfolio is checked by something other than the labeller's opinion*. That something is execution, replay, verbatim source matching, a policy engine, or a second annotator.

## Why these projects (research, November 2026)

- **Demand has moved from volume to expert evaluation.** Agentic AI has driven a shift from large-scale labelling to tasks that need expert evaluation ([Wikipedia: Data annotation](https://en.wikipedia.org/wiki/Data_annotation)). Current postings include chain-of-thought evaluation, process reward annotation and agentic code evaluation, at $40–130/hr for coding experts ([OpenTrain jobs](https://www.opentrain.ai/jobs/), [aitraining.jobs](https://aitraining.jobs/roles/data-labeling)).
- **Rubrics are now part of the reward.** Specific, non-overlapping rubric criteria give more reliable reward signals, and vague criteria weaken judging and RL fine-tuning ([Snorkel: RL environments](https://snorkel.ai/blog/rl-environments-for-llm-agents-design-rewards-and-validation/), [Rubrics across the LLM landscape](https://arxiv.org/html/2606.08625v2)). Human-written rubrics reportedly beat model-written ones by a wide margin, and synthetic rubrics show diminishing returns ([Expert Rubrics for RLVR](https://arxiv.org/html/2606.09118v3)).
- **Step-level agent and reasoning labels.** Dense per-step rubric rewards for trajectories ([AdaRubric](https://arxiv.org/pdf/2603.21362)). First-error labelling is the process-reward convention, and agent process benchmarks report agreement on thousands of human step labels using an error-propagation rule ([arXiv 2603.14465](https://arxiv.org/pdf/2603.14465)).
- **Hiring is portfolio-first.** Screening increasingly combines an AI-led interview with automated review of the candidate's portfolio and code history. Production pipelines route the least-confident LLM-judge labels to human experts ([HeroHunt 2026 guide](https://www.herohunt.ai/blog/data-annotator-recruiting-ai-labs-2026/)). Platforms test "rubric application and accuracy over time" ([Mercor](https://mercor.com/resources/experts/what-is-an-ai-trainer/), [annotation.academy](https://annotation.academy/careers/how-to-get-ai-training-jobs-remote)).

Some cited preprints are very recent. Verify each before quoting it in an application.

## The projects

| # | Project | Shows | Verified by | Status |
|---|---|---|---|---|
| 1 | Preference ranking (annotation-qa-kit, task 1) | rubric use, rationale quality, IAA | consistency rules, alpha/kappa | **built** |
| 2 | Code evaluation (task 2) | finding bugs, smallest failing input | hidden tests + reference execution | **built** |
| 3 | Factuality / grounding (task 3) | claim decomposition, evidence | verbatim quote matching | **built** |
| 4 | **Agent trajectory evaluation** (task 4) | step labels, first error, policy violations, harmful actions, prompt injection | deterministic **environment replay** + **policy-as-code** | **built (this round)** |
| 5 | **Rubric authoring for RL rewards** (task 5) | writing atomic, weighted, checkable criteria | a rubric **linter**, per-criterion inter-rater reliability, and **discrimination** (does the rubric separate good from bad responses?) | **built (this round)** |
| 6 | **Process-reward (step-level reasoning) labels** (task 6) | first-error step, error type, the right-answer/wrong-process trap | exact fraction re-check of every calculation + hidden first-error truth | **built** |
| 7 | LLM-judge audit | judge vs human gold, position and verbosity bias | swapped-order and padded-response probes | next |
| 8 | Red-team set with harm taxonomy | attack design, severity, refusal boundaries | ATP's red-team harness (ledger proof) | later |
| 9 | Case study: pre-registered benchmark annotations (ATP) | annotation methodology at scale: pre-registration, change log, frozen tag | git history | later |

## Standards every project meets

1. **Versioned guidelines** with definitions, anchors, edge cases and a changelog.
2. **Original data.** No copied benchmark items, and fictional entities where facts would otherwise need lookup.
3. **A mechanical check** that catches a labeller who is wrong or lazy, so quality is not taken on trust.
4. **Agreement and gold accuracy**, with undefined statistics reported as undefined.
5. **An adjudication queue** ranked by severity.
6. **Honest provenance.** Synthetic annotators are labelled synthetic, and AI assistance is disclosed.
7. **Green CI.** Tests prove every planted defect is caught.

## What only the portfolio owner can do (the part that gets you hired)

The tooling and reference labels were built with AI assistance. What proves *your* skill is your own labelling:

1. Label every dataset yourself, blind: don't open `data/**/labels/reference.jsonl` first.
2. Run the checks on your labels and record your real numbers in `RESULTS.md`, for example "found 7/7 contradictions; caught the chunk() test gap; outcome accuracy 8/8 on trajectories". Disagreeing with the reference is fine **if your rationale is better**: write it up in an adjudication note. That is exactly what reviewers want to see.
3. Write one short post per project ("what I learned labelling agent trajectories").
4. Get one other person to label one task, and publish the real inter-annotator agreement.

## Timeline

| When | Milestone |
|---|---|
| Week 1 | Projects 4–5 built (done); you label tasks 1–3 blind and write RESULTS.md |
| Week 2 | You label tasks 4–6; project 6 (process rewards) built |
| Week 3 | Build project 7 (judge audit); recruit a second annotator for one task |
| Week 4 | Case study (9), portfolio landing page, posts; start applying |
| Ongoing | Project 8 (red team) once ATP 1.0 ships |
