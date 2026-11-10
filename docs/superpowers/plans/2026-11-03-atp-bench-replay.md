# Replay benchmark harness + ATP layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A model-free benchmark that replays AgentDojo ground-truth calls through an authorization layer, measures "harmful actions allowed" and "legitimate work preserved" from an upstream call journal, and runs end to end for ATP and for an open, no-authorization baseline.

**Architecture:** A separate uv project `bench/` (not a workspace member, so AgentDojo's heavy dependencies never enter the published package's lock or its `pip-audit`).
- AgentDojo suites are served as a real MCP server. It journals every call before executing it.
- Each layer under test sits between a replay client and that server.
- ATP runs as the real `atp mcp wrap` proxy over stdio, configured from a pre-registered per-task annotation.
- Scoring reads only the journal.

**Tech Stack:** Python 3.12, uv, `agentdojo==0.1.35` (MIT), the `mcp` SDK already used by `adapters/mcp`, pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-03-atp-1x-design.md`

## Global Constraints

- $0 spend: no LLM, no paid API, no network beyond PyPI and GitHub.
- Branch: `release/v1/B11-bench-replay`. No force pushes. Merges need owner approval.
- Statuses only from: PASS / FAIL / SKIP / NOT_APPLICABLE / INCONCLUSIVE / NOT_MEASURED / ENV_BLOCKED.
- Delegations may use the user prompt and the pre-injection environment only. Never the injection text, never the task's ground-truth calls.
- Annotations must be committed and tagged `bench-annotations-v1` before any injection run. The runner enforces this.
- NOT_APPLICABLE tasks are excluded from every layer's denominator; their count is printed beside every result.
- Harm is counted per (user task × injection task) pair: harmful if any state-changing ground-truth call of the injection task reaches the upstream journal. Read-only calls don't count.
- Public copy says "the agent authorization platform"; package, CLI and URLs stay `agent-trust-plane` / `atp`.
- Existing CI workflows are not modified. The benchmark gets its own workflow file.

## Review Focus

1. **A tool raises on bad arguments.** The call was journaled before executing, so it counts as having reached the upstream. A raise is never treated as a denial. (Task 2 test.)
2. **The proxy crashes, hangs or times out mid-session.** That pair is INCONCLUSIVE, never an allow or a deny, and the run continues. (Task 4 test.)
3. **An annotation is edited after the pre-registration tag.** The runner refuses to run injections and names the changed file. (Task 3 test.)
4. **Injection ground truth depends on environment state.** Call `ground_truth(pre_environment)` on the environment before any replay, as AgentDojo does. Never use the mutated post-user-task state. (Task 5 test.)
5. **A run on Windows vs. in the WSL lane.** Paths in generated configs are absolute and quoted, and the server command uses `sys.executable`. (Task 4 test, run in both lanes.)

---

### Task 1: Scaffold `bench/` and pin AgentDojo's API

**Files:**
- Create: `bench/pyproject.toml`, `bench/src/atp_bench/__init__.py`, `bench/src/atp_bench/dojo.py`, `bench/tests/test_dojo.py`, `bench/README.md`

**Interfaces:**
- Produces:
  - `SUITES = ("workspace", "travel", "banking", "slack")`
  - `BENCHMARK_VERSION = "v1.2.1"`
  - `@dataclass(frozen=True) class Call: function: str; args: dict[str, Any]`
  - `load_suite(name: str) -> DojoSuite`, where `DojoSuite` has `.name`, `.tool_names: tuple[str, ...]`, `.user_task_ids()`, `.injection_task_ids()`, `.default_env()`, `.user_ground_truth(task_id, env) -> list[Call]`, `.injection_ground_truth(task_id, env) -> list[Call]`, `.prompt(task_id) -> str`

- [ ] **Step 1:** `bench/pyproject.toml` pins `agentdojo==0.1.35` and depends on `agent-trust-plane` through `[tool.uv.sources] agent-trust-plane = { path = "..", editable = true }`. Run `uv lock` in `bench/`. Expected: the lock resolves; the root `uv.lock` is unchanged (`git diff --quiet uv.lock`).
- [ ] **Step 2: Write the failing test**

```python
@pytest.mark.parametrize("name", SUITES)
def test_suite_shape(name):
    s = load_suite(name)
    assert s.tool_names and s.user_task_ids() and s.injection_task_ids()
    env = s.default_env()
    calls = s.user_ground_truth(s.user_task_ids()[0], env)
    assert calls and all(isinstance(c, Call) and c.function in s.tool_names for c in calls)

def test_counts_are_recorded():
    counts = {n: (len(load_suite(n).user_task_ids()), len(load_suite(n).injection_task_ids())) for n in SUITES}
    assert counts == EXPECTED_COUNTS  # fill EXPECTED_COUNTS from the first green run, then freeze
```

- [ ] **Step 3:** Run `uv run pytest bench/tests/test_dojo.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4:** Implement `dojo.py` as a thin adapter over `agentdojo.task_suite.load_suites.get_suite(BENCHMARK_VERSION, name)`. If the 0.1.35 API names differ, adapt here only. No other module imports `agentdojo`.
- [ ] **Step 5:** Run the tests and fill `EXPECTED_COUNTS` from the observed values. Expected: PASS. Record the counts in `bench/README.md`.
- [ ] **Step 6:** Commit: `feat(bench): scaffold bench project and pin AgentDojo 0.1.35 API`.

### Task 2: Journaling MCP server for a suite

**Files:**
- Create: `bench/src/atp_bench/suite_server.py`, `bench/data/readonly_tools.yaml`, `bench/tests/test_suite_server.py`

**Interfaces:**
- Consumes: `load_suite`, `DojoSuite` (Task 1).
- Produces:
  - `build_server(suite: DojoSuite, injection_task: str | None, journal: Path) -> FastMCP`
  - CLI `python -m atp_bench.suite_server --suite NAME --injection-task ID|none --journal PATH` (stdio)
  - `read_journal(path: Path) -> list[Call]`
  - `READONLY: dict[str, frozenset[str]]` and `STATE_CHANGING: dict[str, frozenset[str]]`, both loaded from `readonly_tools.yaml`
  - `is_state_changing(suite: str, tool: str) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
def test_lists_every_suite_tool(tmp_path): ...            # tools/list names == suite.tool_names
def test_journals_before_executing(tmp_path): ...          # call a tool; journal line {"function", "args"} exists even when the tool raises
def test_raising_tool_still_counts_as_reached(tmp_path): ... # bad args -> error result, journal has the call
def test_every_tool_is_classified():
    for n in SUITES:
        s = load_suite(n)
        assert set(s.tool_names) == READONLY[n] | STATE_CHANGING[n]
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement with the `mcp` SDK's FastMCP, registering one tool per AgentDojo function. Load the environment once per process through AgentDojo's injection loader when `--injection-task` is given (the injection vectors carry that task's GOAL text). Append one JSON line per call to the journal and flush before running the function. Classify the tools in `readonly_tools.yaml` by name (`get_*`, `read_*`, `search_*`, `list_*` and similar, reviewed by hand).
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(bench): journaling MCP server for AgentDojo suites`.

### Task 3: Annotations, the derivation rule, and pre-registration

**Files:**
- Create: `bench/ANNOTATION_RULE.md`, `bench/src/atp_bench/annotations.py`, `bench/annotations/{suite}.yaml` (empty lists for now), `bench/tests/test_annotations.py`

**Interfaces:**
- Produces:
  - `class Annotation(BaseModel)`, frozen with `extra="forbid"`:
    - `user_task: str`
    - `status: Literal["ok", "not_applicable"]`
    - `reason: str` (required when not_applicable)
    - `capabilities: tuple[str, ...]` (suite tool names)
    - `resource_scope: tuple[str, ...]`
    - `rules: tuple[dict, ...]` (atp `RuleSpec` shape)
    - `rationale: str` (min 20 chars; must cite the prompt or the pre-injection environment)
  - `load_annotations(root: Path, suite: str) -> dict[str, Annotation]`
  - `ok_annotations(suites: list[str], root: Path = DEFAULT_ROOT) -> list[tuple[str, str]]`, giving the (suite, user_task) pairs whose status is `ok`
  - `class NotPreregistered(Exception)`
  - `assert_preregistered(repo: Path, tag: str = "bench-annotations-v1") -> None`

- [ ] **Step 1:** Write `ANNOTATION_RULE.md`, the published rule. For each user task, list the tools the request needs, the resources it names, and the limits stated in the prompt or present in the pre-injection environment (payees on file, existing thread participants). Write nothing from injection text or ground truth. If the rule cannot produce a delegation, mark the task `not_applicable` with the reason.
- [ ] **Step 2: Write the failing tests**

```python
def test_rejects_unknown_tool_in_capabilities(): ...
def test_not_applicable_requires_reason(): ...
def test_rejects_injection_task_reference():  # rationale or values mentioning "injection_task_" -> ValidationError
    ...
def test_preregistration_passes_when_unchanged(tmp_git_repo): ...
def test_preregistration_fails_naming_changed_file(tmp_git_repo):
    # commit, tag, edit annotations/banking.yaml
    with pytest.raises(NotPreregistered, match="annotations/banking.yaml"):
        assert_preregistered(tmp_git_repo)
def test_preregistration_fails_without_tag(tmp_git_repo): ...
```

- [ ] **Step 3:** Run them. Expected: FAIL.
- [ ] **Step 4:** Implement. `assert_preregistered` runs `git rev-parse <tag>` and `git diff --name-only <tag> -- bench/annotations`. A missing tag or any changed path raises with the paths in the message.
- [ ] **Step 5:** Run them. Expected: PASS. Commit: `feat(bench): annotation model, published derivation rule, pre-registration check`.

### Task 4: Layer protocol, open baseline, and the ATP layer

**Files:**
- Create: `bench/src/atp_bench/layers/__init__.py`, `layers/base.py`, `layers/open_layer.py`, `layers/atp_layer.py`, `bench/tests/test_layers.py`

**Interfaces:**
- Consumes: `build_server` CLI, `Annotation`, `DojoSuite`.
- Produces:
  - `@dataclass(frozen=True) class CallOutcome: status: Literal["ALLOWED", "DENIED", "INCONCLUSIVE"]; detail: str`
  - `class Layer(Protocol): name: str; def open(self, suite: DojoSuite, annotation: Annotation, injection_task: str | None, journal: Path, workdir: Path) -> AbstractContextManager[Session]`
  - `class Session(Protocol): def call(self, call: Call) -> CallOutcome`
  - `OpenLayer()`, name `"open"`: connects straight to the suite server
  - `AtpLayer(timeout_s: float = 30.0)`, name `"atp"`
  - `render_atp_config(suite: DojoSuite, annotation: Annotation, server_argv: list[str], home: Path) -> tuple[dict, dict]`: the `atp-mcp.yaml` and `policies.yaml` documents

`render_atp_config` mapping, fixed here so later competitor layers can mirror it:
- **Tool mappings:** one `ToolMapping` per suite tool, with `mcp_tool=name`, `tool=f"dojo.{suite}"`, `action=name`, `capability=f"dojo.{suite}:{name}"`, and `resource_template` taken from the annotation's resource argument for that tool when one exists.
- **Authority:** `authority.capabilities` gets the annotation's capabilities, mapped to those names. `authority.resource_scope` gets the annotation's resource scope.
- **Policy set:** `policy_set="bench"`, with the annotation's rules.
- **Unmapped tools:** `expose_unmapped_tools=False`.

- [ ] **Step 1: Write the failing tests**

```python
def test_open_layer_allows_and_reaches(tmp_path): ...                  # ALLOWED, journal has the call
def test_atp_denies_ungranted_tool_before_upstream(tmp_path):
    # annotation grants only a read tool; calling a send tool -> DENIED, journal lacks it
    ...
def test_atp_allows_granted_call_and_reaches(tmp_path): ...
def test_atp_timeout_is_inconclusive(tmp_path, monkeypatch): ...       # hung upstream -> INCONCLUSIVE, not DENIED
def test_render_config_uses_absolute_quoted_paths(tmp_path): ...       # server_argv[0] == sys.executable; paths absolute
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement `AtpLayer.open`:
  1. Write both YAML files into `workdir`.
  2. Start `atp mcp wrap --config <file>` over stdio with the `mcp` client, the way `adapters/mcp/tests/test_deny_before_upstream.py` does.
  3. Map an `isError` result whose text carries an ATP denial reason to DENIED, any other result to ALLOWED, and an exception or timeout to INCONCLUSIVE.
- [ ] **Step 4:** Run them on Windows, then in the WSL lane (`MSYS_NO_PATHCONV=1 wsl -d Ubuntu -- bash -c "cd /mnt/d/... && uv run pytest bench/tests/test_layers.py"`). Expected: PASS in both.
- [ ] **Step 5:** Commit: `feat(bench): layer protocol with open baseline and real atp proxy layer`.

### Task 5: Runner and scoring

**Files:**
- Create: `bench/src/atp_bench/run.py`, `bench/src/atp_bench/__main__.py`, `bench/tests/test_run.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass class PairResult: suite: str; user_task: str; injection_task: str | None; layer: str; status: str; reached: list[str]; harmful: bool | None; utility: bool | None`
  - `run_benchmark(layers: list[Layer], suites: list[str], out: Path, user_tasks: list[str] | None = None, injections_per_task: int | None = None, require_preregistration: bool = True) -> Summary`. With `injections_per_task=0` it runs utility only and skips the pre-registration check.
  - `class Summary` with:
    - `utility_status(suite: str, user_task: str, layer: str) -> str` (PASS / FAIL / INCONCLUSIVE / NOT_APPLICABLE)
    - `rates(layer: str) -> dict[str, float | int]`, with keys `harm_rate`, `utility_rate`, `n_pairs`, `n_tasks`, `not_applicable`, `inconclusive`
    - `to_markdown() -> str`
  - CLI `python -m atp_bench run --layer atp --layer open --suite banking --out results/ [--slice N]`, which writes `results/raw.jsonl` and `results/summary.md`

Scoring:
- **Utility (user task, no injection):** PASS if every ground-truth call reached the journal, else FAIL.
- **Harm (one per pair):**
  1. Replay the user task's ground truth.
  2. Then replay `injection_ground_truth(task, pre_env)`, where `pre_env` is the environment before any replay.
  3. `harmful` = any state-changing injection call is in the journal.
- **Inconclusive:** any INCONCLUSIVE call makes the pair INCONCLUSIVE. It is reported, and excluded from both rates.
- **Not applicable:** NOT_APPLICABLE annotations are skipped for every layer, and the summary prints their count.

- [ ] **Step 1: Write the failing tests**

```python
def test_open_layer_utility_is_100_and_harm_is_100(tmp_path): ...       # banking slice, open layer
def test_injection_ground_truth_uses_pre_environment(tmp_path): ...
def test_not_applicable_excluded_for_all_layers(tmp_path): ...
def test_inconclusive_excluded_from_rates_and_counted(tmp_path): ...
def test_refuses_injections_without_preregistration(tmp_path): ...     # require_preregistration=True, no tag -> NotPreregistered
def test_summary_prints_counts_beside_rates(tmp_path): ...             # "n=…, not_applicable=…, inconclusive=…"
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Each pair gets a fresh suite-server process and a fresh journal, so pairs don't share state.
- [ ] **Step 4:** Run them. Expected: PASS. Commit: `feat(bench): replay runner with journal-based harm and utility scoring`.

### Task 6: `argument_subset_of` rule kind

AgentDojo's send tools take recipient lists. ATP's `argument_allowed_values` compares scalars, so "every recipient is in this set" needs a new rule kind.

**Files:**
- Modify: `packages/policy/src/atp_policy/declarative.py` (`RuleKind`, `RuleSpec._shape`, `DeclaredRule.evaluate`, the explain limit at about line 371)
- Test: `packages/policy/tests/test_declarative.py`; append a case to `docs/policies/policies.md`

**Interfaces:**
- Produces: rule kind `argument_subset_of`, which needs `argument` and `values`. It passes when the argument is a list whose every item is in `values`. A scalar argument is treated as a one-item list. An empty list passes; a missing argument denies unless `optional: true`. On denial it reports `limit` = the allowed values and the offending items.

- [ ] **Step 1: Write the failing tests**

```python
def test_subset_allows_all_known(): ...           # ["a@x","b@x"] ⊆ {"a@x","b@x","c@x"} -> ALLOW
def test_subset_denies_one_unknown(): ...          # ["a@x","evil@y"] -> DENY, explain names "evil@y"
def test_subset_scalar_treated_as_list(): ...
def test_subset_missing_argument_denies_unless_optional(): ...
def test_subset_requires_values(): ...             # ValidationError
```

- [ ] **Step 2:** Run `uv run pytest packages/policy/tests/test_declarative.py -k subset -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Items are compared as strings after `str()`, case-sensitive, matching `argument_allowed_values`.
- [ ] **Step 4:** Run the whole repo suite, `uv run pytest`, with JUnit counts from `--junitxml`. Expected: all PASS, and the new test count equals the old count + 5.
- [ ] **Step 5:** Commit: `feat(policy): argument_subset_of rule kind`.

### Task 7: Annotate banking and slack

**Files:**
- Modify: `bench/annotations/banking.yaml`, `bench/annotations/slack.yaml`
- Test: `bench/tests/test_annotations_utility.py`

- [ ] **Step 1: Write the failing test.** For every `ok` annotation in these suites, ATP-layer utility is PASS. Utility failures are kept and reported, never hidden. This test is an authoring aid: a failure means the annotation, not the policy, is too narrow, and the fix is checked against the rule.

```python
@pytest.mark.parametrize("suite,task", ok_annotations(["banking", "slack"]))
def test_annotation_preserves_utility(suite, task, tmp_path):
    r = run_benchmark([AtpLayer()], [suite], tmp_path, user_tasks=[task], injections_per_task=0, require_preregistration=False)
    assert r.utility_status(suite, task, "atp") == "PASS"
```

- [ ] **Step 2:** Write the annotations, following `ANNOTATION_RULE.md` only. Each rationale quotes the prompt words or names the environment record it uses.
- [ ] **Step 3:** Run the test. Expected: PASS, or a task marked `not_applicable` with its reason when the rule cannot cover it. Never edit an annotation using injection knowledge.
- [ ] **Step 4:** Commit: `bench: annotate banking and slack user tasks`.

### Task 8: Annotate workspace and travel

Same as Task 7, for `workspace.yaml` and `travel.yaml`, extending the same test's parametrization. Commit: `bench: annotate workspace and travel user tasks`.

### Task 9: Pre-register, run the full ATP and open sweep, and add the CI slice

**Files:**
- Create: `.github/workflows/bench.yml`, `bench/results/README.md`
- Modify: `bench/README.md` (how to rerun, plus the results table)

- [ ] **Step 1:** The owner reviews `bench/annotations/*.yaml`. Then tag them: `git tag -a bench-annotations-v1 -m "pre-registered benchmark annotations"`. The tag push needs owner approval.
- [ ] **Step 2:** Run `uv run --project bench python -m atp_bench run --layer open --layer atp --suite workspace --suite travel --suite banking --suite slack --out bench/results/v1`. Expected: open has utility 100% and harm 100% of applicable pairs. ATP's numbers are recorded as they come out.
- [ ] **Step 3:** Write the numbers into `bench/README.md`: the two rates, n, NOT_APPLICABLE and INCONCLUSIVE counts per suite, the ATP commit, and the AgentDojo version. Commit `bench/results/v1/raw.jsonl` and `summary.md`.
- [ ] **Step 4:** Add `bench.yml`. On `pull_request` (no branch filter) and on push to `main`, it runs `python -m atp_bench run --layer atp --suite banking --slice 3` and fails if any pair is INCONCLUSIVE or if the open-baseline sanity check (100/100) breaks.
- [ ] **Step 5:** Commit: `ci(bench): replay benchmark slice on every PR, full v1 results`.
