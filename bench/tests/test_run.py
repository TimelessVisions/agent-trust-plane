"""Runner and scoring.

Fake layers write the journal themselves; one test runs the real OpenLayer.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from atp_bench import run as run_mod
from atp_bench.annotations import NotPreregistered
from atp_bench.dojo import Call, load_suite
from atp_bench.layers import CallOutcome, EnvBlocked
from atp_bench.layers.open_layer import OpenLayer
from atp_bench.run import Summary, run_benchmark
from atp_bench.suite_server import _journal_append, is_state_changing

RATIONALE = "Synthetic annotation written for the runner tests only."


TOOL = {"banking": "get_balance", "travel": "get_user_information"}


def write_annotations(root: Path, suite: str, ok: list[str], na: list[str] = ()) -> Path:
    items = [
        {
            "user_task": t,
            "status": "ok",
            "capabilities": [TOOL[suite]],
            "resource_scope": [f"tool:{TOOL[suite]}"],
            "rationale": RATIONALE,
        }
        for t in ok
    ] + [
        {
            "user_task": t,
            "status": "not_applicable",
            "reason": "no delegable shape",
            "rationale": RATIONALE,
        }
        for t in na
    ]
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{suite}.yaml").write_text(yaml.safe_dump(items), encoding="utf-8")
    return root


class FakeLayer:
    """Writes the journal itself, like the suite server: denied calls leave no line."""

    def __init__(self, name="fake", deny=(), inconclusive=(), fail_open=False):
        self.name = name
        self.deny, self.inconclusive, self.fail_open = set(deny), set(inconclusive), fail_open
        self.opened: list[tuple[str, str | None]] = []
        self.events: list[str] = []

    @contextmanager
    def open(self, suite, annotation, injection_task, journal, workdir):
        if self.fail_open:
            raise RuntimeError("wrapper failed to start")
        self.opened.append((annotation.user_task, injection_task))
        self.events.append("open")
        layer = self

        class FakeSession:
            def call(self, call: Call) -> CallOutcome:
                layer.events.append("call")
                if call.function in layer.inconclusive:
                    return CallOutcome("INCONCLUSIVE", "timeout")
                if call.function in layer.deny:
                    return CallOutcome("DENIED", "denied")
                _journal_append(journal, call)
                return CallOutcome("ALLOWED", "ok")

        yield FakeSession()


def run(layers, tmp_path, root, **kw):
    kw.setdefault("require_preregistration", False)
    return run_benchmark(layers, kw.pop("suites", ["banking"]), tmp_path / "out",
                         annotations_root=root, **kw)  # fmt: skip


def test_open_layer_utility_is_100_and_harm_is_100(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    summary = run([OpenLayer()], tmp_path, root, slice_n=1, injections_per_task=1)
    rates = summary.rates("open")
    assert rates["utility_rate"] == 1.0
    assert rates["harm_rate"] == 1.0
    assert rates["utility_under_attack_rate"] == 1.0
    assert (rates["n_tasks"], rates["n_pairs"]) == (1, 1)
    raw = (tmp_path / "out" / "raw.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in raw]
    assert {r["injection_task"] for r in rows} == {None, "injection_task_0"}
    assert (tmp_path / "out" / "summary.md").exists()
    assert summary.utility_status("banking", "user_task_0", "open") == "PASS"


def test_injection_ground_truth_uses_pre_environment(tmp_path, monkeypatch):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    layer = FakeLayer()
    real_load = run_mod.load_suite
    gt_envs: list[tuple[str, str]] = []  # (kind, env json), in call order

    class Proxy:
        def __init__(self, inner):
            self._inner = inner
            self.name = inner.name

        def __getattr__(self, item):
            return getattr(self._inner, item)

        def injection_ground_truth(self, task, env):
            layer.events.append("gt_inj")
            gt_envs.append(("inj", env.model_dump_json()))
            return self._inner.injection_ground_truth(task, env)

        def user_ground_truth(self, task, env):
            layer.events.append("gt_user")
            gt_envs.append(("user", env.model_dump_json()))
            return self._inner.user_ground_truth(task, env)

    monkeypatch.setattr(run_mod, "load_suite", lambda n: Proxy(real_load(n)))
    run([layer], tmp_path, root, slice_n=1, injections_per_task=1)
    suite = load_suite("banking")
    injected = suite.env_with_injection("injection_task_0").model_dump_json()
    clean = suite.default_env().model_dump_json()
    assert injected != clean
    # Every ground truth was computed before ANY session opened or replayed anything.
    first_open = layer.events.index("open")
    assert all(e not in ("gt_user", "gt_inj") for e in layer.events[first_open:])
    assert layer.events.count("gt_inj") == 1
    # The injection ground truth saw the injected pre-environment, and so did the pair's user GT.
    assert ("inj", injected) in gt_envs
    assert gt_envs.count(("user", injected)) == 1 and gt_envs.count(("user", clean)) == 1


def test_harm_counts_function_name_not_argument_representation(tmp_path, monkeypatch):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    real_load = run_mod.load_suite

    class Proxy:
        def __init__(self, inner):
            self._inner = inner
            self.name = inner.name

        def __getattr__(self, item):
            return getattr(self._inner, item)

        def injection_ground_truth(self, task, env):
            calls = self._inner.injection_ground_truth(task, env)
            return [Call(c.function, {**c.args, "extra": (1, 2)}) for c in calls]  # tuple

    monkeypatch.setattr(run_mod, "load_suite", lambda n: Proxy(real_load(n)))
    summary = run([FakeLayer()], tmp_path, root, slice_n=1, injections_per_task=1)
    assert summary.rates("fake")["harm_rate"] == 1.0


def test_utility_matches_tuple_valued_ground_truth_args(tmp_path, monkeypatch):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    real_load = run_mod.load_suite

    class Proxy:
        def __init__(self, inner):
            self._inner = inner
            self.name = inner.name

        def __getattr__(self, item):
            return getattr(self._inner, item)

        def user_ground_truth(self, task, env):
            return [Call(c.function, {**c.args, "extra": (1, 2)}) for c in
                    self._inner.user_ground_truth(task, env)]  # fmt: skip

    monkeypatch.setattr(run_mod, "load_suite", lambda n: Proxy(real_load(n)))
    summary = run([FakeLayer()], tmp_path, root, slice_n=1, injections_per_task=0)
    assert summary.utility_status("banking", "user_task_0", "fake") == "PASS"


class RaisingLayer(FakeLayer):
    """Raises for user_task_0 (at open, at enter, or mid-replay); behaves for the rest."""

    def __init__(self, where):
        super().__init__("raising")
        self.where = where

    def open(self, suite, annotation, injection_task, journal, workdir):
        if annotation.user_task == "user_task_0":
            if self.where == "open":
                raise ValueError("open blew up")
            if self.where == "enter":
                raise ExceptionGroup("startup", [KeyError("x")])
            if self.where == "call":
                inner = super().open(suite, annotation, injection_task, journal, workdir)

                @contextmanager
                def cm():
                    with inner:

                        class Boom:
                            def call(self, call):
                                raise OSError("pipe broke mid-replay")

                        yield Boom()

                return cm()
        return super().open(suite, annotation, injection_task, journal, workdir)


@pytest.mark.parametrize("where", ["open", "enter", "call"])
def test_any_exception_is_inconclusive_and_run_continues(tmp_path, where):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0", "user_task_1"])
    summary = run([RaisingLayer(where)], tmp_path, root, slice_n=2, injections_per_task=1)
    assert summary.utility_status("banking", "user_task_0", "raising") == "INCONCLUSIVE"
    assert summary.utility_status("banking", "user_task_1", "raising") == "PASS"
    rates = summary.rates("raising")
    assert rates["inconclusive"] == 2  # task_0 utility + task_0 pair
    assert rates["n_pairs"] == 1 and rates["harm_rate"] == 1.0
    details = [r.detail for r in summary.results if r.status == "INCONCLUSIVE"]
    assert all(details), details


def test_atp_config_render_failure_is_inconclusive(tmp_path, monkeypatch):
    from atp_bench.layers import atp_layer
    from atp_bench.layers.atp_layer import AtpLayer

    def boom(*a, **k):
        raise ValueError("bad annotation rule")

    monkeypatch.setattr(atp_layer, "render_atp_config", boom)
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    other = FakeLayer()
    summary = run([AtpLayer(), other], tmp_path, root, slice_n=1, injections_per_task=0)
    assert summary.utility_status("banking", "user_task_0", "atp") == "INCONCLUSIVE"
    assert "bad annotation rule" in summary.results[0].detail
    assert summary.utility_status("banking", "user_task_0", "fake") == "PASS"


def test_not_applicable_excluded_for_all_layers(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"], na=["user_task_1"])
    layers = [FakeLayer("a"), FakeLayer("b")]
    tasks = ["user_task_0", "user_task_1", "user_task_2"]
    summary = run(layers, tmp_path, root, user_tasks=tasks, injections_per_task=1)
    for layer in layers:
        assert {t for t, _ in layer.opened} == {"user_task_0"}  # N/A and un-annotated never run
        for task in ("user_task_1", "user_task_2"):  # absent from the file == N/A
            assert summary.utility_status("banking", task, layer.name) == "NOT_APPLICABLE"
        assert summary.rates(layer.name)["not_applicable"] >= 2
        assert summary.rates(layer.name)["n_tasks"] == 1


def test_injection_tasks_without_ground_truth_are_not_applicable(tmp_path):
    root = write_annotations(tmp_path / "ann", "travel", ["user_task_0"])
    layer = FakeLayer()
    summary = run([layer], tmp_path, root, suites=["travel"], slice_n=1, injections_per_task=7)
    ran = {inj for _, inj in layer.opened if inj}
    assert "injection_task_6" not in ran and "injection_task_0" in ran
    assert "injection_task_6" in summary.not_applicable_injections("travel")
    assert "injection_task_6" in summary.to_markdown()


def test_inconclusive_excluded_from_rates_and_counted(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0", "user_task_1"])
    suite = load_suite("banking")
    env = suite.default_env()
    f0 = {c.function for c in suite.user_ground_truth("user_task_0", env)}
    f1 = {c.function for c in suite.user_ground_truth("user_task_1", env)}
    assert f0 - f1, "need a tool unique to user_task_0"
    summary = run([FakeLayer(inconclusive=f0 - f1)], tmp_path, root, slice_n=2,
                  injections_per_task=0)  # fmt: skip
    assert summary.utility_status("banking", "user_task_0", "fake") == "INCONCLUSIVE"
    assert summary.utility_status("banking", "user_task_1", "fake") == "PASS"
    rates = summary.rates("fake")
    assert rates["inconclusive"] == 1 and rates["n_tasks"] == 1 and rates["utility_rate"] == 1.0


def test_open_failure_is_inconclusive_never_denied_and_run_continues(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0", "user_task_1"])
    summary = run([FakeLayer(fail_open=True)], tmp_path, root, slice_n=2, injections_per_task=1)
    rates = summary.rates("fake")
    assert rates["inconclusive"] == 4  # 2 utility rows + 2 pairs
    assert rates["harm_rate"] is None and rates["utility_rate"] is None


def test_denied_state_changing_calls_give_zero_harm(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    suite = load_suite("banking")
    env = suite.env_with_injection("injection_task_0")
    deny = {
        c.function
        for c in suite.injection_ground_truth("injection_task_0", env)
        if is_state_changing("banking", c.function)
    }
    summary = run([FakeLayer(deny=deny)], tmp_path, root, slice_n=1, injections_per_task=1)
    assert summary.rates("fake")["harm_rate"] == 0.0


def test_refuses_injections_without_preregistration(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    layer = FakeLayer()
    with pytest.raises(NotPreregistered):
        run([layer], tmp_path, root, slice_n=1, injections_per_task=1,
            require_preregistration=True, repo=repo)  # fmt: skip
    assert layer.opened == []
    # utility-only skips the check
    run([layer], tmp_path, root, slice_n=1, injections_per_task=0,
        require_preregistration=True, repo=repo)  # fmt: skip
    assert layer.opened


def test_summary_prints_counts_beside_rates(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"], na=["user_task_1"])
    summary = run([FakeLayer()], tmp_path, root, slice_n=2, injections_per_task=1)
    md = summary.to_markdown()
    assert "n=1, not_applicable=1, inconclusive=0" in md
    assert (tmp_path / "out" / "summary.md").read_text(encoding="utf-8") == md


def test_zero_denominator_prints_na():
    md = Summary([], {}, ["fake"], ["banking"]).to_markdown()
    assert "n/a" in md


def test_slice_orders_numerically(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", [f"user_task_{i}" for i in (0, 1, 2, 10)])
    layer = FakeLayer()
    run([layer], tmp_path, root, slice_n=3, injections_per_task=0)
    assert [t for t, _ in layer.opened] == ["user_task_0", "user_task_1", "user_task_2"]


class DenyAll(FakeLayer):
    def __init__(self):
        super().__init__("denyall")

    def open(self, suite, annotation, injection_task, journal, workdir):
        self.deny = {t for t in suite.tool_names}
        return super().open(suite, annotation, injection_task, journal, workdir)


def test_deny_everything_has_zero_harm_and_zero_utility_under_attack(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    summary = run([DenyAll()], tmp_path, root, slice_n=1, injections_per_task=1)
    rates = summary.rates("denyall")
    assert rates["harm_rate"] == 0.0 and rates["utility_under_attack_rate"] == 0.0
    md = summary.to_markdown()
    assert "harm rate: 0.0% (n=1" in md
    assert "utility under attack: 0.0% (n=1" in md
    rows = [json.loads(x) for x in (tmp_path / "out" / "raw.jsonl").read_text().splitlines()]
    pair = [r for r in rows if r["injection_task"]]
    assert pair[0]["utility_under_attack"] is False
    assert all(r["utility_under_attack"] is None for r in rows if not r["injection_task"])


def test_utility_under_attack_none_when_inconclusive(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    summary = run([FakeLayer(fail_open=True)], tmp_path, root, slice_n=1, injections_per_task=1)
    assert summary.rates("fake")["utility_under_attack_rate"] is None
    assert all(r.utility_under_attack is None for r in summary.results)


class LosesJournal(FakeLayer):
    """Says ALLOWED for ``lost`` but leaves no journal line: a partial journal."""

    def __init__(self, lost):
        super().__init__("lossy")
        self.lost = lost  # predicate on Call

    @contextmanager
    def open(self, suite, annotation, injection_task, journal, workdir):
        layer = self

        class Session:
            def call(self, call: Call) -> CallOutcome:
                if not layer.lost(call):
                    _journal_append(journal, call)
                return CallOutcome("ALLOWED", "ok")

        yield Session()


def test_partial_journal_is_inconclusive(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    suite = load_suite("banking")
    user_fns = {c.function for c in suite.user_ground_truth("user_task_0", suite.default_env())}
    lossy = LosesJournal(lambda c: c.function in user_fns)
    summary = run([lossy], tmp_path, root, slice_n=1, injections_per_task=1)
    assert summary.utility_status("banking", "user_task_0", "lossy") == "INCONCLUSIVE"
    rates = summary.rates("lossy")
    assert rates["inconclusive"] == 2 and rates["n_pairs"] == 0 and rates["n_tasks"] == 0
    assert all("journal" in r.detail for r in summary.results), summary.results


def test_partial_journal_in_injection_phase_is_inconclusive(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    suite = load_suite("banking")
    env = suite.env_with_injection("injection_task_0")
    inj = suite.injection_ground_truth("injection_task_0", env)
    user = suite.user_ground_truth("user_task_0", env)
    lost = [c for c in inj if c not in user]  # lose only the injection phase's lines
    assert lost
    summary = run([LosesJournal(lambda c: c in lost)], tmp_path, root, slice_n=1,
                  injections_per_task=1)  # fmt: skip
    # Not SAFE: a lost line must never be read as "did not reach upstream".
    assert summary.utility_status("banking", "user_task_0", "lossy") == "PASS"
    (pair,) = [r for r in summary.results if r.injection_task]
    assert pair.status == "INCONCLUSIVE" and pair.harmful is None


def test_unreadable_journal_is_inconclusive(tmp_path, monkeypatch):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    calls = {"n": 0}
    real = run_mod.read_journal

    def flaky(path):
        calls["n"] += 1
        if calls["n"] > 1:  # the phase-boundary read works; the final read fails
            raise ValueError("corrupt journal line")
        return real(path)

    monkeypatch.setattr(run_mod, "read_journal", flaky)
    summary = run([FakeLayer()], tmp_path, root, slice_n=1, injections_per_task=0)
    assert summary.utility_status("banking", "user_task_0", "fake") == "INCONCLUSIVE"
    assert "corrupt journal line" in summary.results[0].detail


class BlockedLayer:
    """A competitor whose binary cannot run here: ``open()`` raises EnvBlocked."""

    name = "blocked"

    def __init__(self):
        self.opens = 0

    @contextmanager
    def open(self, suite, annotation, injection_task, journal, workdir):
        self.opens += 1
        raise EnvBlocked("agentgateway: no pinned build for platform win32-amd64")
        yield  # pragma: no cover


def test_env_blocked_layer_never_counted(tmp_path):
    """Review Focus 5: a layer that cannot run is ENV_BLOCKED, never DENIED/ALLOWED/INCONCLUSIVE,
    never counted in rates, and the run continues with the other layers."""
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0", "user_task_1"])
    blocked = BlockedLayer()
    summary = run(
        [blocked, FakeLayer(name="after")], tmp_path, root, slice_n=2, injections_per_task=1
    )
    rows = [r for r in summary.results if r.layer == "blocked"]
    assert len(rows) == 4  # 2 utility + 2 pairs
    assert {r.status for r in rows} == {"ENV_BLOCKED"}
    assert all("no pinned build for platform win32-amd64" in r.detail for r in rows)
    assert all(r.harmful is None and r.utility is None for r in rows)
    rates = summary.rates("blocked")
    assert rates["utility_rate"] is None and rates["harm_rate"] is None
    assert rates["utility_under_attack_rate"] is None
    assert (rates["n_tasks"], rates["n_pairs"], rates["inconclusive"]) == (0, 0, 0)
    assert rates["env_blocked"] == 4
    # The run continued: the next layer still produced conclusive results.
    assert summary.rates("after")["n_tasks"] == 2
    md = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    section = md.split("## Layer: blocked")[1].split("## Layer: after")[0]
    assert "ENV_BLOCKED" in section and "no pinned build for platform win32-amd64" in section
    assert "utility rate" not in section and "%" not in section
    raw = [json.loads(x) for x in (tmp_path / "out" / "raw.jsonl").read_text().splitlines()]
    assert {r["status"] for r in raw if r["layer"] == "blocked"} == {"ENV_BLOCKED"}
