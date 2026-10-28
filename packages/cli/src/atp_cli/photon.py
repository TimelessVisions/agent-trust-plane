"""Explicit, outbound-only Photon alerts from verified ATP denial traces.

This adapter is deliberately NOT part of authorization or execution. It reads a
completed trace and may send a privacy-minimal notification. It cannot approve
an action, issue a grant, or alter a decision.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from atp_core import DecisionOutcome
from atp_gateway.service import TraceView

API_BASE = "https://api.photon.codes/v1/projects"
PHONE_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
TRACE_RE = re.compile(r"^[A-Za-z0-9_-]{6,128}$")


class PhotonAlertError(ValueError):
    """A safe-to-display failure without credentials or sensitive payloads."""


def denial_alert(view: TraceView) -> str:
    """Use only integrity and structured decision metadata, never raw arguments."""
    if not view.integrity.valid:
        raise PhotonAlertError("trace integrity verification failed; no alert sent")
    decision = view.decision
    if decision is None:
        raise PhotonAlertError("trace contains no recorded authorization decision")
    if decision.trace_id != view.trace_id:
        raise PhotonAlertError("decision and trace identifiers disagree")
    if not TRACE_RE.fullmatch(view.trace_id):
        raise PhotonAlertError("trace identifier is not safe for a text notification")
    if decision.enforcement != "enforce":
        raise PhotonAlertError("shadow-mode observations cannot be sent as blocked-action alerts")
    if decision.outcome is not DecisionOutcome.DENY:
        raise PhotonAlertError("only enforced DENY decisions can trigger this alert")

    # The reason code is a fixed ATP enum, not an agent-controlled explanation.
    return (
        "AGENT TRUST PLANE\n"
        "Decision: DENY (enforced)\n"
        f"Trace: {view.trace_id}\n"
        f"Reason: {decision.reason_code.value}\n"
        "ATP withheld authorization. Review the trace locally for details.\n"
        "Read-only notification. Text replies cannot approve actions."
    )


@dataclass(frozen=True)
class PhotonCredentials:
    project_id: str
    api_key: str
    agent_user_id: str

    def validate(self) -> None:
        if not ID_RE.fullmatch(self.project_id):
            raise PhotonAlertError("PHOTON_PROJECT_ID is missing or malformed")
        if not self.api_key or any(c in self.api_key for c in "\r\n"):
            raise PhotonAlertError("PHOTON_API_KEY is missing or malformed")
        if not ID_RE.fullmatch(self.agent_user_id):
            raise PhotonAlertError("PHOTON_AGENT_USER_ID is missing or malformed")


class PhotonClient:
    def __init__(self, credentials: PhotonCredentials) -> None:
        credentials.validate()
        self.credentials = credentials
        self.base = f"{API_BASE}/{quote(credentials.project_id, safe='')}"

    def _post(self, path: str, payload: dict[str, Any], *, request_key: str) -> dict[str, Any]:
        # Reusing a key makes retries idempotent within Photon's retention window.
        # This is not a durable exactly-once guarantee.
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, request_key))
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = Request(
            self.base + path,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.credentials.api_key}",
                "Content-Type": "application/json",
                "idempotency-key": key,
            },
        )
        try:
            with urlopen(req, timeout=12) as response:
                if not 200 <= response.status < 300:
                    raise PhotonAlertError(f"Photon API rejected {path} (HTTP {response.status})")
                raw = response.read(65536)
        except HTTPError as exc:
            raise PhotonAlertError(f"Photon API rejected {path} (HTTP {exc.code})") from exc
        except (URLError, TimeoutError, OSError) as exc:
            # Do not automatically retry: acceptance may have happened remotely.
            raise PhotonAlertError(
                "Photon request failed or outcome is unknown; check Photon logs before retrying"
            ) from exc
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PhotonAlertError("Photon returned an invalid JSON response") from exc
        if not isinstance(result, dict):
            raise PhotonAlertError("Photon returned an unexpected response type")
        return result

    def send_denial(self, recipient: str, trace_id: str, message: str) -> str:
        if not PHONE_RE.fullmatch(recipient):
            raise PhotonAlertError("recipient must be an E.164 phone number, such as +12125550123")
        customer = self._post(
            "/users",
            {"platform": "imessage", "handle": recipient},
            request_key=f"atp:{self.credentials.project_id}:user:{recipient}",
        )
        customer_id = customer.get("id")
        if not isinstance(customer_id, str) or not ID_RE.fullmatch(customer_id):
            raise PhotonAlertError("Photon did not return a valid recipient user ID")
        space = self._post(
            "/spaces",
            {
                "platform": "imessage",
                "participantIds": [self.credentials.agent_user_id, customer_id],
            },
            request_key=f"atp:{self.credentials.project_id}:space:{self.credentials.agent_user_id}:{customer_id}",
        )
        space_id = space.get("id")
        if not isinstance(space_id, str) or not ID_RE.fullmatch(space_id):
            raise PhotonAlertError("Photon did not return a valid conversation space ID")
        sent = self._post(
            "/messages",
            {
                "spaceId": space_id,
                "senderId": self.credentials.agent_user_id,
                "content": {"type": "text", "format": "plain", "text": message},
            },
            request_key=f"atp:{self.credentials.project_id}:denial:{trace_id}:{recipient}",
        )
        msg_id = sent.get("id")
        if not isinstance(msg_id, str) or not ID_RE.fullmatch(msg_id):
            raise PhotonAlertError(
                "Photon accepted the request but returned no recognizable message ID; inspect logs"
            )
        return msg_id
