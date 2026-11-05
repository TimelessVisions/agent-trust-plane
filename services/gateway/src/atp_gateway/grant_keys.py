"""Grant key storage, loading and rotation.

A keys directory holds, per key id (``kid``):

    grant-<kid>.key      PKCS8 PEM private key, mode 0600 where the OS allows
    grant-<kid>.pub      SubjectPublicKeyInfo PEM public key
    grant-<kid>.retired  ISO-8601 UTC time the key stopped signing (rotation)

The active key is named by ``ATP_GRANT_SIGNING_KID`` in an env-style file
(``.atp/keys.env`` or the ``.env`` of ``atp serve``); the private key itself is
never written into an env file. ``rotate_grant_key`` makes a new active key and
retires the old one: its private key is deleted, its public key keeps verifying
for one grant TTL after the time in its ``.retired`` file, then it is ignored.
A ``.pub`` that is neither active nor retired is never trusted.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

from atp_core import utcnow
from atp_gateway.grants import GrantSigner, GrantVerifier, kid_for
from atp_identity.keys import ensure_private_dir, write_file_atomic

KID_ENV = "ATP_GRANT_SIGNING_KID"
KEYS_DIR_ENV = "ATP_GRANT_KEYS_DIR"
LEGACY_HMAC_ENV = "ATP_GRANT_SIGNING_KEY"
_KID_RE = re.compile(r"^[0-9a-f]{16}$")


def private_key_path(keys_dir: Path, kid: str) -> Path:
    return Path(keys_dir) / f"grant-{kid}.key"


def public_key_path(keys_dir: Path, kid: str) -> Path:
    return Path(keys_dir) / f"grant-{kid}.pub"


def retired_marker_path(keys_dir: Path, kid: str) -> Path:
    return Path(keys_dir) / f"grant-{kid}.retired"


def _check_kid(kid: str) -> str:
    if not _KID_RE.match(kid):
        raise ValueError(f"invalid grant kid {kid!r}; expected 16 lowercase hex characters")
    return kid


def _ensure_dir(keys_dir: Path) -> None:
    ensure_private_dir(keys_dir)


def generate_grant_key(keys_dir: Path) -> str:
    """Create a new Ed25519 key pair in ``keys_dir`` and return its kid."""
    keys_dir = Path(keys_dir)
    _ensure_dir(keys_dir)
    key = Ed25519PrivateKey.generate()
    kid = kid_for(key.public_key())
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    write_file_atomic(private_key_path(keys_dir, kid), pem, private=True)
    write_file_atomic(public_key_path(keys_dir, kid), pub, private=False)
    return kid


def load_signer(keys_dir: Path, kid: str) -> GrantSigner:
    path = private_key_path(Path(keys_dir), _check_kid(kid))
    key = load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    if kid_for(key.public_key()) != kid:
        raise ValueError(f"{path} does not hold the key for kid {kid}")
    return GrantSigner(key, kid)


def load_public_key(keys_dir: Path, kid: str) -> Ed25519PublicKey:
    path = public_key_path(Path(keys_dir), _check_kid(kid))
    key = load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"{path} is not an Ed25519 public key")
    if kid_for(key) != kid:
        raise ValueError(f"{path} does not hold the key for kid {kid}")
    return key


# A ``.retired`` time may be this far ahead of the verifier's clock (skew
# between the host that rotated and the one verifying); more is a config error.
RETIRED_CLOCK_SKEW = timedelta(minutes=5)


def retired_at(keys_dir: Path, kid: str, *, now: datetime | None = None) -> datetime | None:
    """When ``kid`` stopped signing, or None if it was never retired.

    A time more than ``RETIRED_CLOCK_SKEW`` in the future is refused: it would
    stretch the old key's verification window past one TTL.
    """
    path = retired_marker_path(Path(keys_dir), kid)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    when = datetime.fromisoformat(text)
    if when.tzinfo is None:
        raise ValueError(f"{path} must hold a timezone-aware ISO-8601 time")
    if when > (now or utcnow()) + RETIRED_CLOCK_SKEW:
        raise ValueError(
            f"{path} holds a retirement time in the future ({when.isoformat()}); "
            "fix the file or the clock"
        )
    return when


@dataclass(frozen=True)
class GrantKeyring:
    signer: GrantSigner
    verifier: GrantVerifier
    retired: dict[str, datetime] = field(default_factory=dict)  # kid -> verify-until


def load_grant_keys(
    keys_dir: Path,
    active_kid: str,
    *,
    grant_ttl_seconds: int,
    now: datetime | None = None,
) -> GrantKeyring:
    """The active signer plus every retired public key still inside its window.

    A retired key verifies until ``retired_at + grant_ttl_seconds``; the
    verifier also enforces that deadline at verification time, so a
    long-running gateway drops it on schedule.
    """
    keys_dir = Path(keys_dir)
    now = now or utcnow()
    signer = load_signer(keys_dir, active_kid)
    public: dict[str, Ed25519PublicKey] = {signer.kid: signer.public_key}
    not_after: dict[str, datetime] = {}
    for pub in sorted(keys_dir.glob("grant-*.pub")):
        kid = pub.name[len("grant-") : -len(".pub")]
        if kid == active_kid or not _KID_RE.match(kid):
            continue
        when = retired_at(keys_dir, kid, now=now)
        if when is None:
            continue  # neither active nor retired: never trusted
        deadline = when + timedelta(seconds=grant_ttl_seconds)
        if now >= deadline:
            continue
        public[kid] = load_public_key(keys_dir, kid)
        not_after[kid] = deadline
    verifier = GrantVerifier(public, not_after=not_after)
    return GrantKeyring(signer=signer, verifier=verifier, retired=not_after)


def ephemeral_keyring() -> GrantKeyring:
    """A per-process key for ``:memory:`` gateways (tests, in-process demos)."""
    key = Ed25519PrivateKey.generate()
    signer = GrantSigner(key, kid_for(key.public_key()))
    return GrantKeyring(signer=signer, verifier=GrantVerifier({signer.kid: signer.public_key}))


def retire_grant_key(keys_dir: Path, kid: str, *, now: datetime | None = None) -> None:
    """Mark ``kid`` retired at ``now`` (kept if already marked) and delete its
    private key so it can never sign again. Idempotent."""
    keys_dir = Path(keys_dir)
    marker = retired_marker_path(keys_dir, _check_kid(kid))
    if not marker.exists():
        when = (now or utcnow()).isoformat()
        write_file_atomic(marker, f"{when}\n".encode("ascii"), private=False)
    with contextlib.suppress(FileNotFoundError):
        private_key_path(keys_dir, kid).unlink()


# ------------------------------------------------------------------ env files
def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def update_env_file(
    path: Path, *, set_values: dict[str, str], remove: frozenset[str] = frozenset()
) -> None:
    """Rewrite ``KEY=VALUE`` lines in place, keeping comments and order.

    Keys in ``set_values`` replace an existing line or are appended; keys in
    ``remove`` are dropped. The file is replaced atomically with mode 0600.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    pending = dict(set_values)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key and not line.lstrip().startswith("#"):
            if key in remove and key not in pending:
                continue
            if key in pending:
                out.append(f"{key}={pending.pop(key)}")
                continue
        out.append(line)
    out.extend(f"{k}={v}" for k, v in pending.items())
    write_file_atomic(path, ("\n".join(out) + "\n").encode("utf-8"), private=True)


def rotate_grant_key(
    keys_dir: Path, env_path: Path, *, now: datetime | None = None
) -> tuple[str, str]:
    """Make a new active grant key and retire the current one.

    Order matters for a crash at any step: the new key is written first, then
    the old key's ``.retired`` marker, then the env file is switched to the new
    key, and only then is the old private key deleted. A crash before the
    switch leaves the old key active and still able to sign (an active kid's
    marker is ignored; a re-run rewrites it); a crash after it leaves the
    old key already marked, so it keeps verifying for one TTL and is never
    stranded as an untrusted, unmarked ``.pub``.
    Returns ``(old_kid, new_kid)``.
    """
    keys_dir = Path(keys_dir)
    old = read_env_file(env_path).get(KID_ENV, "")
    if not old:
        raise ValueError(f"{env_path} has no {KID_ENV}; nothing to rotate")
    _check_kid(old)
    new = generate_grant_key(keys_dir)
    # ``old`` is still active, so any marker it has is left over from an
    # interrupted rotation; this rotation's time replaces it.
    when = (now or utcnow()).isoformat()
    write_file_atomic(
        retired_marker_path(keys_dir, old), f"{when}\n".encode("ascii"), private=False
    )
    update_env_file(env_path, set_values={KID_ENV: new}, remove=frozenset({LEGACY_HMAC_ENV}))
    retire_grant_key(keys_dir, old, now=now)
    return old, new
