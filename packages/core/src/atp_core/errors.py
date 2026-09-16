from __future__ import annotations

from atp_core.reasons import ReasonCode


class ATPError(Exception):
    """Base class for all domain errors. Carries a machine-readable reason code."""

    def __init__(self, reason_code: ReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


class DelegationError(ATPError):
    """Raised when a delegation cannot be issued or resolved."""


class EnvelopeError(ATPError):
    """Raised when an envelope is structurally invalid for the requested operation."""


class GrantError(ATPError):
    """Raised when an execution grant fails verification."""


class ToolError(ATPError):
    """Raised by a tool during execution."""
