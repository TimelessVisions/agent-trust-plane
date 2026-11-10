"""D4: Docker MCP Gateway environment handling and an explicit name-only reference."""

from __future__ import annotations

import subprocess

import pytest
from atp_bench.annotations import DEFAULT_ROOT, load_annotations
from atp_bench.dojo import Call, load_suite
from atp_bench.layers.base import EnvBlocked
from atp_bench.layers.docker_layer import DockerMcpLayer
from atp_bench.layers.name_only_layer import NameOnlyLayer
from atp_bench.suite_server import read_journal


def _banking():
    return load_suite("banking"), load_annotations(DEFAULT_ROOT, "banking")["user_task_0"]


def test_docker_absent_is_env_blocked(tmp_path, monkeypatch):
    suite, ann = _banking()

    def no_daemon(command, **kwargs):
        assert command[:2] == ["docker", "info"]
        return subprocess.CompletedProcess(command, 1, "", "Cannot connect to Docker daemon")

    monkeypatch.setattr("atp_bench.layers.docker_layer.subprocess.run", no_daemon)
    with (
        pytest.raises(EnvBlocked, match=r"Docker engine unavailable:.*Cannot connect"),
        DockerMcpLayer().open(
            suite, ann, None, tmp_path / "journal.jsonl", tmp_path / "docker-work"
        ),
    ):
        pytest.fail("a missing Docker daemon must never authorize or deny a call")


def test_name_only_allows_granted_tool_with_any_args(tmp_path):
    suite, ann = _banking()
    journal = tmp_path / "journal.jsonl"
    with NameOnlyLayer().open(suite, ann, None, journal, tmp_path / "work") as session:
        result = session.call(
            Call(
                "send_money",
                {
                    "recipient": "acct-not-in-scope",
                    "amount": 9999,
                    "subject": "test",
                    "date": "2022-01-01",
                },
            )
        )
    assert result.status == "ALLOWED"
    assert [c.function for c in read_journal(journal)] == ["send_money"]


def test_name_only_denies_ungranted_tool(tmp_path):
    suite, ann = _banking()
    journal = tmp_path / "journal.jsonl"
    with NameOnlyLayer().open(suite, ann, None, journal, tmp_path / "work") as session:
        result = session.call(Call("update_password", {"password": "x"}))
    assert result.status == "DENIED"
    assert read_journal(journal) == []
