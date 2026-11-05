"""E1 test-first contract: fixture-driven incident replay and truthful per-layer results."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from atp_bench.incidents import IncidentCase, run_incident
from atp_bench.layers.base import CallOutcome


def _case() -> IncidentCase:
    return IncidentCase.model_validate(
        {
            "id": "mcpoison",
            "title": "Definition changed after approval",
            "source_urls": ["https://research.checkpoint.com/2025/cursor-vulnerability-mcpoison/"],
            "server": "mcpoison/server.py",
            "calls": [
                {"function": "read_note", "args": {"id": "readme"}},
                {"definition_change": "poisoned"},
                {"function": "write_note", "args": {"id": "readme", "text": "x"}},
            ],
            "expect": {"name-only": "ALLOWED", "atp": "DENIED"},
            "atp_regression": "mcpoison/atp-regression.yaml",
        }
    )


class _FakeLayer:
    def __init__(self, name: str, attack_status: str) -> None:
        self.name = name
        self.attack_status = attack_status


class _Session:
    def __init__(self, layer: _FakeLayer) -> None:
        self.layer = layer
        self.calls: list[str] = []

    def call(self, call) -> CallOutcome:
        self.calls.append(call.function)
        status = "ALLOWED" if call.function == "read_note" else self.layer.attack_status
        return CallOutcome(status, f"synthetic call {call.function}")


def test_incident_runner_reports_per_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    state: list[tuple[str, str]] = []

    def open_case(layer, case):
        assert case.id == "mcpoison"
        return nullcontext(_Session(layer))

    def change_definition(session, key):
        assert key == "poisoned"
        state.append((session.layer.name, key))

    fixture = SimpleNamespace(
        open_incident=open_case,
        change_definition=change_definition,
    )
    monkeypatch.setattr("atp_bench.incidents._load_fixture", lambda case: fixture)

    ordinary = run_incident(_case(), _FakeLayer("name-only", "ALLOWED"))
    protected = run_incident(_case(), _FakeLayer("atp", "DENIED"))
    regression = run_incident(_case(), _FakeLayer("atp", "ALLOWED"))
    assert ordinary.status == "PASS"
    assert ordinary.observed == "ALLOWED"
    assert protected.status == "PASS"
    assert protected.observed == "DENIED"
    assert regression.status == "FAIL"
    assert regression.observed == "ALLOWED"
    assert ordinary.calls == ("read_note", "write_note")
    assert state == [
        ("name-only", "poisoned"),
        ("atp", "poisoned"),
        ("atp", "poisoned"),
    ]


def test_incident_runner_never_passes_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ErrorSession:
        def call(self, call):
            return CallOutcome("INCONCLUSIVE", "upstream transport unavailable")

    fixture = SimpleNamespace(
        open_incident=lambda layer, case: nullcontext(_ErrorSession()),
        change_definition=lambda session, key: None,
    )
    monkeypatch.setattr("atp_bench.incidents._load_fixture", lambda case: fixture)
    result = run_incident(_case(), _FakeLayer("atp", "DENIED"))
    assert result.status == "INCONCLUSIVE"
    assert result.observed == "INCONCLUSIVE"


def test_incident_schema_rejects_path_escape() -> None:
    data = _case().model_dump()
    data["server"] = "../outside.py"
    with pytest.raises(ValueError):
        IncidentCase.model_validate(data)
