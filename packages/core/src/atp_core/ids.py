from __future__ import annotations

import secrets
import uuid


def new_id(prefix: str) -> str:
    """Opaque, unguessable identifier with a readable prefix (e.g. ``grt_``)."""
    return f"{prefix}_{uuid.uuid4().hex}"


def new_secret_key() -> str:
    """A 64-character URL-safe secret that never starts with "-".

    Keys are pasted into command lines (`atp record --operator-key KEY`), and
    argparse reads a leading "-" as another option. token_urlsafe draws one
    about 1 time in 64, so redraw until it does not.
    """
    while True:
        key = secrets.token_urlsafe(48)
        if not key.startswith("-"):
            return key


def new_trace_id() -> str:
    """Short, human-readable trace id. 12 hex chars is plenty for a local audit log."""
    return secrets.token_hex(6)
