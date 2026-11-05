import pytest
from atp_bench.dojo import SUITES, Call, load_suite

EXPECTED_COUNTS: dict[str, tuple[int, int]] = {
    "workspace": (40, 14),
    "travel": (20, 7),
    "banking": (16, 9),
    "slack": (21, 5),
}


@pytest.mark.parametrize("name", SUITES)
def test_suite_shape(name):
    s = load_suite(name)
    assert s.tool_names and s.user_task_ids() and s.injection_task_ids()
    env = s.default_env()
    calls = s.user_ground_truth(s.user_task_ids()[0], env)
    assert calls and all(isinstance(c, Call) and c.function in s.tool_names for c in calls)


def test_counts_are_recorded():
    counts = {
        n: (len(load_suite(n).user_task_ids()), len(load_suite(n).injection_task_ids()))
        for n in SUITES
    }
    assert counts == EXPECTED_COUNTS
