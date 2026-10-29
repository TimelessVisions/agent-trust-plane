from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "founder_demo_server.py"
    spec = importlib.util.spec_from_file_location("founder_demo_server", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transcript_redacts_local_paths_and_is_bounded(tmp_path: Path) -> None:
    module = _module()
    lines = [f"line {index} {tmp_path}" for index in range(100)]
    result = module._redact_output("\n".join(lines), tmp_path)
    assert len(result) == 80
    assert str(tmp_path) not in "\n".join(result)
    assert "<demo-output>" in result[-1]


def test_alert_status_returns_only_delivery_attempt_state(tmp_path: Path) -> None:
    journal = tmp_path / "photon-alerts.db"
    with sqlite3.connect(journal) as conn:
        conn.execute(
            "CREATE TABLE photon_attempts (trace_id TEXT PRIMARY KEY, status TEXT, message_id TEXT)"
        )
        conn.execute(
            "INSERT INTO photon_attempts VALUES ('trace-demo', 'accepted', 'private-message-id')"
        )
    module = _module()
    assert module._alert_status(tmp_path, "trace-demo") == "accepted"
    assert module._alert_status(tmp_path, "missing") is None


def test_trace_payload_handles_serialized_execution_event() -> None:
    module = _module()
    view = SimpleNamespace(
        trace_id="trace-demo",
        envelope=SimpleNamespace(action="write_note", capability="notes:write"),
        decision=SimpleNamespace(outcome="ALLOW", reason_code="ALLOWED", enforcement="enforce"),
        execution={"event_type": "execution_completed"},
        integrity=SimpleNamespace(valid=True, event_count=8, head_hash="abc"),
    )
    payload = module._trace_payload(view)
    assert payload["executed"] is True
    assert payload["integrity_valid"] is True
