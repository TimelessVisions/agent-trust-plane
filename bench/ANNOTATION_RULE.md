# Annotation derivation rule (published)

Each AgentDojo user task gets one annotation: the delegation a careful human would
grant to an agent asked to do that task, and nothing wider. Annotations live in
`bench/annotations/{workspace,travel,banking,slack}.yaml` and are pre-registered by
the git tag `bench-annotations-v1` before any benchmark run. Changing one afterwards
makes `assert_preregistered` fail.

## Allowed sources

1. The user task prompt text (`user_task.PROMPT`), read as written.
2. The pre-injection environment state: the default environment with no injection
   text, for example payees already on file, existing channel or thread participants,
   calendar entries, file names, hotel and restaurant listings.

## Forbidden sources

- Injection task text, goals, or ids, in any form.
- Ground-truth call lists, for user tasks or injection tasks.
- Any knowledge of which attacks exist, what they target, or what a defence would
  need to block them. The annotator must not ask "what would stop attack X".
- Results of earlier benchmark runs.

An annotation that names `injection_task_*` is rejected by the loader.

## What an annotation contains

For each task, from the allowed sources only:

- `capabilities`: the suite tool names the request needs. Include a tool only if the
  prompt cannot be satisfied without it. Reads needed to find a value count.
- `resource_scope`: the resources those tools may touch, as `dojo.<suite>:<id>` or
  `tool:<name>` patterns. Use a resource the prompt names or the environment holds.
- `resource_args`: for tools whose resource comes from an argument, which argument
  names it (for example the recipient or channel).
- `rules`: limits stated in the prompt (an amount, a recipient) or present in the
  environment (the payees on file, the people already on a thread). Use
  `argument_subset_of` to confine a list argument to a known set.
- `rationale`: at least 20 characters. It must quote the prompt words, or name the
  environment record, that justify each capability, scope and rule. If you cannot
  point to either, the entry does not belong in the annotation.

## When a task is `not_applicable`

Set `status: not_applicable` with a `reason` when the sources above cannot yield a
delegation narrower than the whole tool set. Examples: the prompt names no target and
the environment offers no bounded set to choose from; or the task is to act on
whatever content it finds, so any tool and any target is in scope. Do not mark a task
not applicable because it looks hard to defend, or because of what an attack could do.
A `not_applicable` entry carries no capabilities, scope, or rules, and is excluded
from the evaluated set by `ok_annotations`.

## Same annotation for every layer

Competitor defence layers and ATP receive the same annotation for a task. Each layer
is configured from it by a fixed rendering step. No layer gets a hand-tuned variant,
and the annotation is never edited per layer.
