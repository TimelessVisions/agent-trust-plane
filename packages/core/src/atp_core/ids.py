from __future__ import annotations

import secrets
import uuid


def new_id(prefix: str) -> str:
    """Opaque, unguessable identifier with a readable prefix (e.g. ``grt_``)."""
    return f"{prefix}_{uuid.uuid4().hex}"


def new_trace_id() -> str:
    """Short, human-readable trace id. 12 hex chars is plenty for a local audit log."""
    return secrets.token_hex(6)
