"""Use Photon Spectrum SDK for outbound read-only ATP denial alerts.

Runs the source-tree JavaScript bridge, passing only an already-validated
denial alert on stdin. Never forwards raw traces or allows text approvals.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from atp_cli.photon import PHONE_RE, PhotonAlertError

BRIDGE = Path(__file__).resolve().parents[4] / "integrations" / "photon-spectrum" / "send.mjs"


@dataclass(frozen=True)
class SpectrumCredentials:
    project_id: str


class SpectrumClient:
    """Adapter matching the small send_denial interface of the REST client."""

    def __init__(self, channel: str = "imessage") -> None:
        if channel not in ("imessage", "telegram"):
            raise PhotonAlertError("Unsupported Spectrum messaging channel")
        self.channel = channel
        project_id = os.environ.get("SPECTRUM_PROJECT_ID", "")
        if not project_id or not os.environ.get("SPECTRUM_PROJECT_SECRET"):
            raise PhotonAlertError("SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET are required")
        if channel == "telegram" and not os.environ.get("SPECTRUM_TELEGRAM_BOT_TOKEN"):
            raise PhotonAlertError("SPECTRUM_TELEGRAM_BOT_TOKEN is required")
        # Isolate watcher journals by transport+platform to prevent cross-channel collision.
        self.credentials = SpectrumCredentials(project_id=f"{project_id}:spectrum:{channel}")
        if shutil.which("node") is None:
            raise PhotonAlertError("Node.js is required to run the Spectrum bridge")
        if not BRIDGE.is_file():
            raise PhotonAlertError("Spectrum bridge unavailable; use the ATP source checkout")
        if not (BRIDGE.parent / "node_modules" / "spectrum-ts").is_dir():
            raise PhotonAlertError(
                "Install Spectrum first: npm install --prefix integrations/photon-spectrum"
            )

    def send_denial(self, recipient: str, trace_id: str, message: str) -> str:
        if self.channel == "imessage":
            if not PHONE_RE.fullmatch(recipient):
                raise PhotonAlertError("Invalid E.164 recipient phone number")
        elif not re.fullmatch(r"[1-9][0-9]{4,19}", recipient):
            raise PhotonAlertError("Telegram recipient must be a numeric user ID")
        if not trace_id:
            raise PhotonAlertError("Missing ATP trace ID")
        try:
            result = subprocess.run(
                ["node", str(BRIDGE), *(
                    ["telegram", recipient] if self.channel == "telegram" else [recipient]
                )],
                input=message,
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PhotonAlertError(
                "Spectrum send outcome unknown; inspect Photon and device before retrying"
            ) from exc
        if result.returncode != 0:
            raise PhotonAlertError(
                "Spectrum request failed or outcome unknown; inspect Photon and device"
            )
        # SDK currently reports completion, not a verified delivery or message ID.
        return "spectrum-request-" + trace_id
