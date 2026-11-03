"""Authoring aid: every ``ok`` annotation must keep the user task's utility under ATP.

A failure means the annotation, not the policy, is too narrow. Any change made after a failure
must be justified from the prompt or a named environment record and listed in
``bench/annotations/CHANGES-AFTER-UTILITY.md``; otherwise the failure stands (xfail with reason).
"""

import pytest

from atp_bench.annotations import ok_annotations
from atp_bench.layers.atp_layer import AtpLayer
from atp_bench.run import run_benchmark

# (suite, task) -> reason. Utility failures are results, not bugs: they are kept and reported.
KNOWN_UTILITY_FAILURES: dict[tuple[str, str], str] = {}


def _params():
    out = []
    for suite, task in ok_annotations(["banking", "slack"]):
        reason = KNOWN_UTILITY_FAILURES.get((suite, task))
        marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
        out.append(pytest.param(suite, task, marks=marks, id=f"{suite}-{task}"))
    return out


@pytest.mark.parametrize("suite,task", _params())
def test_annotation_preserves_utility(suite, task, tmp_path):
    r = run_benchmark(
        [AtpLayer()],
        [suite],
        tmp_path,
        user_tasks=[task],
        injections_per_task=0,
        require_preregistration=False,
    )
    status = r.utility_status(suite, task, "atp")
    detail = [x for x in r.results if x.user_task == task and x.injection_task is None]
    assert status == "PASS", detail
