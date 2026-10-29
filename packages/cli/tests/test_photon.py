from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.error import HTTPError

import pytest

from atp_cli import main as cli
from atp_cli.photon import (
    PhotonAlertError,
    PhotonClient,
    PhotonCredentials,
    denial_alert,
)
from atp_core import DecisionOutcome
from atp_gateway.service import TraceView

TRACE_ID = "trc_example123"


def _view(
    *,
    valid: bool = True,
    enforcement: str = "enforce",
    outcome: DecisionOutcome = DecisionOutcome.DENY,
) -> TraceView:
    return cast(
        TraceView,
        SimpleNamespace(
            trace_id=TRACE_ID,
            integrity=SimpleNamespace(valid=valid),
            decision=SimpleNamespace(
                trace_id=TRACE_ID,
                enforcement=enforcement,
                outcome=outcome,
                reason_code=SimpleNamespace(value="CAPABILITY_NOT_GRANTED"),
                explanation="private contents: NEVER SEND",
                evaluations=[{"secret": "NEVER SEND"}],
            ),
            envelope=SimpleNamespace(arguments={"password": "NEVER SEND"}),
        ),
    )


def test_denial_message_is_minimal_and_does_not_copy_private_fields() -> None:
    message = denial_alert(_view())
    assert "DENY (enforced)" in message
    assert TRACE_ID in message
    assert "CAPABILITY_NOT_GRANTED" in message
    assert "NEVER SEND" not in message
    assert "Text replies cannot approve actions" in message


@pytest.mark.parametrize(
    ("valid", "enforcement", "outcome"),
    [
        (False, "enforce", DecisionOutcome.DENY),
        (True, "shadow", DecisionOutcome.DENY),
        (True, "enforce", DecisionOutcome.ALLOW),
        (True, "enforce", DecisionOutcome.REQUIRE_APPROVAL),
    ],
)
def test_refuses_unverified_or_not_enforced_denials(
    valid: bool, enforcement: str, outcome: DecisionOutcome
) -> None:
    with pytest.raises(PhotonAlertError):
        denial_alert(_view(valid=valid, enforcement=enforcement, outcome=outcome))


class _Response:
    status = 202

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _max_bytes: int) -> bytes:
        return self.body


def test_photon_client_posts_verified_shape_without_live_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import atp_cli.photon as photon

    seen: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def fake_open(request: Any, timeout: int) -> _Response:
        assert timeout == 12
        assert request.full_url.startswith("https://api.photon.codes/v1/projects/pho_prj_example")
        body = json.loads(request.data)
        headers = {key.lower(): val for key, val in request.header_items()}
        assert headers["authorization"] == "Bearer test-secret"
        assert headers["idempotency-key"]
        seen.append((request.full_url, body, headers))
        return _Response({"id": ["usr_recipient", "spc_example", "msg_example"][len(seen) - 1]})

    monkeypatch.setattr(photon, "urlopen", fake_open)
    credentials = PhotonCredentials("pho_prj_example", "test-secret", "usr_agent")
    client = PhotonClient(credentials)
    message = denial_alert(_view())
    assert client.send_denial("+12125550123", TRACE_ID, message) == "msg_example"
    assert [u.rsplit("/", 1)[1] for u, _, _ in seen] == ["users", "spaces", "messages"]
    assert seen[0][1] == {"platform": "imessage", "handle": "+12125550123"}
    assert seen[1][1]["participantIds"] == ["usr_agent", "usr_recipient"]
    assert seen[2][1]["content"]["text"] == message
    assert "test-secret" not in str([body for _, body, _ in seen])


def test_invalid_phone_and_credentials_cannot_trigger_network() -> None:
    with pytest.raises(PhotonAlertError):
        PhotonClient(PhotonCredentials("", "secret", "agent"))
    client = PhotonClient(PhotonCredentials("pho_prj_example", "secret", "usr_agent"))
    with pytest.raises(PhotonAlertError):
        client.send_denial("5551234", TRACE_ID, "test")


def test_http_error_does_not_leak_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import atp_cli.photon as photon

    def fail(*_args: object, **_kwargs: object) -> None:
        raise HTTPError("https://api.photon.codes", 401, "secret body", None, None)

    monkeypatch.setattr(photon, "urlopen", fail)
    client = PhotonClient(PhotonCredentials("pho_prj_example", "secret", "usr_agent"))
    with pytest.raises(PhotonAlertError, match="HTTP 401") as exc:
        client.send_denial("+12125550123", TRACE_ID, "test")
    assert "secret body" not in str(exc.value)


def test_cli_dry_run_needs_no_photon_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for name in ("PHOTON_PROJECT_ID", "PHOTON_API_KEY", "PHOTON_AGENT_USER_ID"):
        monkeypatch.delenv(name, raising=False)

    class Runtime:
        trust_plane = SimpleNamespace(get_trace=lambda _trace: _view())

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli, "_open_home", lambda _home: Runtime())
    args = cli.build_parser().parse_args(
        ["photon", "notify", TRACE_ID, "--to", "+12125550123", "--dry-run"]
    )
    assert args.func(args) == 0
    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert TRACE_ID in output
