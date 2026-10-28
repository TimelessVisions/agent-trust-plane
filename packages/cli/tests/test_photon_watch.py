from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from atp_cli.photon import PhotonAlertError
from atp_cli.photon_watch import AlertJournal, process_new_denials, watch
from atp_core import DecisionOutcome


class StubPlane:
    def __init__(self) -> None:
        self.traces: dict[str, Any] = {}

    def add(
        self,
        trace_id: str,
        *,
        outcome: DecisionOutcome = DecisionOutcome.DENY,
        mode: str = "enforce",
        valid: bool = True,
    ) -> None:
        self.traces[trace_id] = SimpleNamespace(
            trace_id=trace_id,
            integrity=SimpleNamespace(valid=valid),
            decision=SimpleNamespace(
                trace_id=trace_id,
                enforcement=mode,
                outcome=outcome,
                reason_code=SimpleNamespace(value="CAPABILITY_NOT_GRANTED"),
            ),
        )

    def list_traces(self, limit: int = 500) -> list[Any]:
        return [SimpleNamespace(trace_id=trace_id) for trace_id in list(self.traces)[-limit:][::-1]]

    def get_trace(self, trace_id: str) -> Any:
        return self.traces[trace_id]


class StubClient:
    credentials = SimpleNamespace(project_id="proj_demo")

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []

    def send_denial(self, _recipient: str, trace_id: str, _message: str) -> str:
        self.sent.append(trace_id)
        if self.fail:
            raise PhotonAlertError("outcome unknown")
        return "msg_demo"


def test_journal_baselines_existing_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "photon-alerts.db"
    j = AlertJournal(path)
    try:
        assert j.initialize(["trc_old1234"], "proj_demo", "+12125550123")
        assert j.status("trc_old1234") == "baseline"
        assert j.claim("trc_old1234") is False
        assert j.claim("trc_new1234") is True
        assert j.claim("trc_new1234") is False
        j.mark_accepted("trc_new1234", "msg_demo")
        assert j.status("trc_new1234") == "accepted"
    finally:
        j.close()
    again = AlertJournal(path)
    try:
        assert not again.initialize(["trc_old1234"], "proj_demo", "+12125550123")
        assert again.status("trc_new1234") == "accepted"
        with pytest.raises(PhotonAlertError, match="already bound"):
            again.initialize([], "proj_other", "+12125550123")
    finally:
        again.close()


def test_watch_new_verified_denials_only(tmp_path: Path) -> None:
    plane = StubPlane()
    plane.add("trc_existing123")
    client = StubClient()
    watch(
        trust_plane=plane,
        home=tmp_path,
        client=client,  # type: ignore[arg-type]
        recipient="+12125550123",
        poll_seconds=1,
        once=True,
    )
    assert client.sent == []
    plane.add("trc_newdeny123")
    plane.add("trc_newallow12", outcome=DecisionOutcome.ALLOW)
    plane.add("trc_newshadow1", mode="shadow")
    plane.add("trc_badchain1", valid=False)
    watch(
        trust_plane=plane,
        home=tmp_path,
        client=client,  # type: ignore[arg-type]
        recipient="+12125550123",
        poll_seconds=1,
        once=True,
    )
    assert client.sent == ["trc_newdeny123"]
    watch(
        trust_plane=plane,
        home=tmp_path,
        client=client,  # type: ignore[arg-type]
        recipient="+12125550123",
        poll_seconds=1,
        once=True,
    )
    assert client.sent == ["trc_newdeny123"]


def test_ambiguous_send_is_never_retried(tmp_path: Path) -> None:
    plane = StubPlane()
    journal = AlertJournal(tmp_path / "photon-alerts.db")
    try:
        assert journal.initialize([], "proj_demo", "+12125550123")
        plane.add("trc_uncertain1")
        client = StubClient(fail=True)
        assert process_new_denials(
            plane,
            journal,
            client,
            "+12125550123",  # type: ignore[arg-type]
        ) == (0, 1)
        assert journal.status("trc_uncertain1") == "unknown"
        assert process_new_denials(
            plane,
            journal,
            client,
            "+12125550123",  # type: ignore[arg-type]
        ) == (0, 0)
        assert client.sent == ["trc_uncertain1"]
    finally:
        journal.close()


def test_watch_rejects_invalid_poll_interval(tmp_path: Path) -> None:
    with pytest.raises(PhotonAlertError, match="poll interval"):
        watch(
            trust_plane=StubPlane(),
            home=tmp_path,
            client=StubClient(),  # type: ignore[arg-type]
            recipient="+12125550123",
            poll_seconds=0,
            once=True,
        )
