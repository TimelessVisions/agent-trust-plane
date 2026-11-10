"""Ed25519 helpers shared by grant keys (gateway) and principal keys (identity).

Kept here, below the gateway, so identity can verify root signatures without
importing the gateway. ``atp_gateway.grants`` and ``atp_gateway.grant_keys``
re-export them under their old names.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from hashlib import sha256
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def kid_for(public_key: Ed25519PublicKey) -> str:
    """``sha256(raw public key).hexdigest()[:16]``."""
    raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return sha256(raw).hexdigest()[:16]


def write_file_atomic(path: Path, data: bytes, *, private: bool) -> None:
    """Write via a temp file in the same directory and ``os.replace``.

    ``private``: the temp file is created with mode 0600 before any byte is
    written, so the secret is never world-readable, even briefly. Windows
    ignores the mode bits; the directory ACL applies there.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        if private:
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
        else:
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o644)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
