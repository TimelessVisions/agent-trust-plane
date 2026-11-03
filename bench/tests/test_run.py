"""Runner and scoring. Fake layers write the journal themselves; one test runs the real OpenLayer."""

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
from atp_bench.layers import CallOutcome
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
    assert (rates["n_tasks"], rates["n_pairs"]) == (1, 1)
    raw = (tmp_path / "out" / "raw.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in raw]
    assert {r["injection_task"] for r in rows} == {None, "injection_task_0"}
    assert (tmp_path / "out" / "summary.md").exists()
    assert summary.utility_status("banking", "user_task_0", "open") == "PASS"


def test_injection_ground_truth_uses_pre_environment(tmp_path, monkeypatch):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"])
    layer = FakeLayer()
    seen: dict = {}
    real_load = run_mod.load_suite

    class Proxy:
        def __init__(self, inner):
            self._inner = inner
            self.name = inner.name

        def __getattr__(self, item):
            return getattr(self._inner, item)

        def injection_ground_truth(self, task, env):
            seen["inj_env"] = env.model_dump_json()
            seen["inj_events"] = list(layer.events)
            return self._inner.injection_ground_truth(task, env)

    monkeypatch.setattr(run_mod, "load_suite", lambda n: Proxy(real_load(n)))
    run([layer], tmp_path, root, slice_n=1, injections_per_task=1)
    suite = load_suite("banking")
    expected = suite.env_with_injection("injection_task_0").model_dump_json()
    assert seen["inj_env"] == expected  # carries the injection goal
    assert expected != suite.default_env().model_dump_json()
    # Computed before the pair's session replayed anything (earlier sessions are utility rows).
    assert seen["inj_events"].count("call") == 0 or seen["inj_events"][-1] != "call"


def test_not_applicable_excluded_for_all_layers(tmp_path):
    root = write_annotations(tmp_path / "ann", "banking", ["user_task_0"], na=["user_task_1"])
    layers = [FakeLayer("a"), FakeLayer("b")]
    summary = run(layers, tmp_path, root,
                  user_tasks=["user_task_0", "user_task_1", "user_task_2"], injections_per_task=1)  # fmt: skip
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
