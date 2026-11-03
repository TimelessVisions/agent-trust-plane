import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from atp_bench.annotations import (
    DEFAULT_ROOT,
    Annotation,
    NotPreregistered,
    assert_preregistered,
    load_annotations,
    ok_annotations,
)
from atp_bench.dojo import SUITES, load_suite

RATIONALE = "Prompt says 'pay the bill from the file'; payee is on file in the environment."


def _ann(**kw):
    base = dict(
        user_task="user_task_0",
        status="ok",
        capabilities=("send_money",),
        resource_scope=("tool:send_money",),
        rules=(),
        rationale=RATIONALE,
    )
    base.update(kw)
    return Annotation(**base)


def _write(root: Path, suite: str, items: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{suite}.yaml").write_text(yaml.safe_dump(items), encoding="utf-8")


def _item(**kw):
    d = dict(
        user_task="user_task_0",
        status="ok",
        capabilities=["send_money"],
        resource_scope=["tool:send_money"],
        rules=[],
        rationale=RATIONALE,
    )
    d.update(kw)
    return d


def test_default_root_is_bench_annotations_and_files_start_empty():
    assert DEFAULT_ROOT.name == "annotations" and DEFAULT_ROOT.parent.name == "bench"
    for s in SUITES:
        assert yaml.safe_load((DEFAULT_ROOT / f"{s}.yaml").read_text()) == []
        assert load_annotations(DEFAULT_ROOT, s) == {}


def test_valid_annotation_loads(tmp_path):
    _write(tmp_path, "banking", [_item()])
    got = load_annotations(tmp_path, "banking")
    assert got["user_task_0"].capabilities == ("send_money",)


def test_rejects_unknown_tool_in_capabilities(tmp_path):
    _write(tmp_path, "banking", [_item(capabilities=["no_such_tool"])])
    with pytest.raises(ValueError, match="no_such_tool"):
        load_annotations(tmp_path, "banking")


def test_rejects_unknown_user_task(tmp_path):
    _write(tmp_path, "banking", [_item(user_task="user_task_9999")])
    with pytest.raises(ValueError, match="user_task_9999"):
        load_annotations(tmp_path, "banking")


def test_rejects_duplicate_user_task(tmp_path):
    _write(tmp_path, "banking", [_item(), _item()])
    with pytest.raises(ValueError, match="duplicate"):
        load_annotations(tmp_path, "banking")


def test_not_applicable_requires_reason():
    with pytest.raises(ValidationError):
        _ann(status="not_applicable", capabilities=(), resource_scope=(), reason="")
    ok = _ann(
        status="not_applicable",
        capabilities=(),
        resource_scope=(),
        reason="Prompt names no recipient or amount; no bounded delegation exists.",
    )
    assert ok.status == "not_applicable"


def test_ok_requires_capabilities():
    with pytest.raises(ValidationError):
        _ann(capabilities=(), resource_scope=())


def test_rejects_injection_task_reference():
    with pytest.raises(ValidationError):
        _ann(rationale="Matches what injection_task_3 would do, so deny it.")
    with pytest.raises(ValidationError):
        _ann(
            rules=(
                {
                    "id": "r1",
                    "applies_to": {"tool": "send_money"},
                    "kind": "argument_allowed_values",
                    "argument": "recipient",
                    "values": ("injection_task_1",),
                },
            )
        )


def test_rationale_min_length():
    with pytest.raises(ValidationError):
        _ann(rationale="too short")


def test_extra_fields_forbidden_and_frozen():
    with pytest.raises(ValidationError):
        _ann(surprise=1)
    with pytest.raises(ValidationError):
        _ann().status = "not_applicable"


def test_bad_scope_pattern_rejected():
    with pytest.raises(ValidationError):
        _ann(resource_scope=("no-colon-here",))


def test_resource_args_must_be_capabilities():
    assert _ann(resource_args={"send_money": "recipient"}).resource_args
    with pytest.raises(ValidationError):
        _ann(resource_args={"get_balance": "x"})


def test_rule_shape_validated():
    good = {
        "id": "amt",
        "applies_to": {"tool": "send_money"},
        "kind": "argument_max",
        "argument": "amount",
        "max": 100,
    }
    assert _ann(rules=(good,)).rules
    with pytest.raises(ValidationError):
        _ann(rules=({**good, "max": None},))
    with pytest.raises(ValidationError):
        _ann(rules=({**good, "kind": "bogus"},))


def test_subset_of_rule_accepted():
    r = {
        "id": "to",
        "applies_to": {"tool": "send_email"},
        "kind": "argument_subset_of",
        "argument": "recipients",
        "values": ("a@example.com",),
    }
    assert _ann(rules=(r,)).rules


def test_ok_annotations_lists_only_ok(tmp_path):
    na = _item(
        user_task="user_task_1",
        status="not_applicable",
        capabilities=[],
        resource_scope=[],
        reason="No bounded delegation can be read off the prompt.",
    )
    _write(tmp_path, "banking", [_item(), na])
    _write(tmp_path, "slack", [])
    assert ok_annotations(["banking", "slack"], root=tmp_path) == [("banking", "user_task_0")]


# ---- pre-registration ----------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def tmp_git_repo(tmp_path):
    repo = tmp_path / "repo"
    ann = repo / "bench" / "annotations"
    ann.mkdir(parents=True)
    for s in SUITES:
        (ann / f"{s}.yaml").write_text("[]\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "tag", "bench-annotations-v1")
    return repo


def test_preregistration_passes_when_unchanged(tmp_git_repo):
    assert_preregistered(tmp_git_repo)


def test_preregistration_ignores_other_paths(tmp_git_repo):
    (tmp_git_repo / "other.txt").write_text("x")
    assert_preregistered(tmp_git_repo)


def test_preregistration_fails_naming_changed_file(tmp_git_repo):
    (tmp_git_repo / "bench/annotations/banking.yaml").write_text("- changed\n")
    with pytest.raises(NotPreregistered, match="annotations/banking.yaml"):
        assert_preregistered(tmp_git_repo)


def test_preregistration_fails_for_committed_change_after_tag(tmp_git_repo):
    (tmp_git_repo / "bench/annotations/slack.yaml").write_text("- changed\n")
    _git(tmp_git_repo, "commit", "-qam", "edit")
    with pytest.raises(NotPreregistered, match="annotations/slack.yaml"):
        assert_preregistered(tmp_git_repo)


def test_preregistration_fails_for_untracked_file(tmp_git_repo):
    (tmp_git_repo / "bench/annotations/extra.yaml").write_text("[]\n")
    with pytest.raises(NotPreregistered, match="annotations/extra.yaml"):
        assert_preregistered(tmp_git_repo)


def test_preregistration_fails_without_tag(tmp_git_repo):
    _git(tmp_git_repo, "tag", "-d", "bench-annotations-v1")
    with pytest.raises(NotPreregistered, match="bench-annotations-v1"):
        assert_preregistered(tmp_git_repo)
