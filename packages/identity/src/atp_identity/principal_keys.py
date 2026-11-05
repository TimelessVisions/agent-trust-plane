"""Human principal keys and signed root delegations.

A root grant (``parent_grant_id is None``) is a human's own statement of the
authority it holds. It must carry an Ed25519 signature by that human's key
over ``root_signing_bytes(grant)``: the canonical JSON of the grant with
``signature``, ``signer_kid`` and ``revoked_at`` left out (revocation is
server state and must not invalidate the signature). ``signer_kid`` is the
first 16 hex characters of SHA-256 over the raw public key, as for grant keys.

Principal keys live in a directory, one pair per principal::

    <principal id>.key   PKCS8 PEM private key, mode 0600 (only where the human signs)
    <principal id>.pub   SubjectPublicKeyInfo PEM public key (what the gateway trusts)

A ``:`` in a principal id is written as ``%3A`` in the file name (Windows).
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
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
from pydantic import ValidationError

from atp_core import DelegationError, ReasonCode, canonical_json, new_id, utcnow
from atp_identity.grants import DelegationGrant
from atp_identity.keys import ensure_private_dir, kid_for, write_file_atomic

ROOT_SIGNATURE_EXCLUDED = frozenset({"signature", "signer_kid", "revoked_at"})


def root_signing_bytes(grant: DelegationGrant) -> bytes:
    """What a human signs: the grant's canonical JSON without the signature
    fields and without ``revoked_at``."""
    # Python mode: canonical_json sorts sets (capabilities) and renders
    # datetimes and Decimals itself, so set iteration order never matters.
    return canonical_json(grant.model_dump(exclude=set(ROOT_SIGNATURE_EXCLUDED)))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_root(grant: DelegationGrant, private_key: Ed25519PrivateKey) -> DelegationGrant:
    """Return ``grant`` signed by ``private_key`` (``signature`` and ``signer_kid`` set)."""
    signature = private_key.sign(root_signing_bytes(grant))
    return grant.model_copy(
        update={"signature": _b64(signature), "signer_kid": kid_for(private_key.public_key())}
    )


class PrincipalKeys(Protocol):
    def public_key(self, principal_id: str) -> Ed25519PublicKey | None:
        """The key the gateway trusts for this principal, or None."""
        ...

    def private_key(self, principal_id: str) -> Ed25519PrivateKey | None:
        """The principal's signing key, where this process holds it, or None."""
        ...


def verify_root(grant: DelegationGrant, keys: PrincipalKeys | None) -> None:
    """Raise ``DelegationError`` unless ``grant`` is signed by its grantor's key."""
    if not grant.signature or not grant.signer_kid:
        raise DelegationError(
            ReasonCode.DELEGATION_ROOT_UNSIGNED,
            f"root grant {grant.grant_id} carries no signature by {grant.grantor}; a root "
            "delegation must be signed by the human's own key (atp principal keygen)",
        )
    public = keys.public_key(grant.grantor.id) if keys is not None else None
    if public is None:
        raise DelegationError(
            ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID,
            f"no public key is registered for {grant.grantor}; cannot verify root grant "
            f"{grant.grant_id}",
        )
    if kid_for(public) != grant.signer_kid:
        raise DelegationError(
            ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID,
            f"root grant {grant.grant_id} was signed by key {grant.signer_kid}, which is not "
            f"{grant.grantor}'s key",
        )
    try:
        public.verify(_unb64(grant.signature), root_signing_bytes(grant))
    except (InvalidSignature, binascii.Error, ValueError) as exc:
        raise DelegationError(
            ReasonCode.DELEGATION_ROOT_SIGNATURE_INVALID,
            f"root grant {grant.grant_id}: the signature does not match its content",
        ) from exc


def sign_root_request(
    body: Mapping[str, Any], keys: PrincipalKeys, *, now: datetime | None = None
) -> dict[str, Any]:
    """Client side: sign a root ``POST /delegations`` body with the grantor's
    key. Fills in ``grant_id`` and ``issued_at`` (they are part of what is
    signed). A body for which ``keys`` holds no private key is returned
    unchanged; the gateway then denies it as unsigned."""
    out = dict(body)
    grantor = out.get("grantor") or {}
    private = keys.private_key(str(grantor.get("id", "")))
    if private is None:
        return out
    out.setdefault("grant_id", new_id("grt"))
    out.setdefault("issued_at", (now or utcnow()).isoformat())
    fields = {k: v for k, v in out.items() if k not in ROOT_SIGNATURE_EXCLUDED}
    try:
        unsigned = DelegationGrant.model_validate(fields)
    except ValidationError:
        return dict(body)  # malformed: let the gateway report what is wrong
    grant = sign_root(unsigned, private)
    dumped = grant.model_dump(mode="json")
    out["issued_at"] = dumped["issued_at"]
    out["signature"] = grant.signature
    out["signer_kid"] = grant.signer_kid
    return out


def _check_id(principal_id: str) -> str:
    # Same alphabet as PrincipalRef.id; no path separators can occur.
    from atp_core import PrincipalKind, PrincipalRef

    PrincipalRef(id=principal_id, kind=PrincipalKind.HUMAN)
    return principal_id


def _stem(principal_id: str) -> str:
    return _check_id(principal_id).replace(":", "%3A")


class InMemoryPrincipalKeys:
    """Keys held in this process (tests, ephemeral gateways)."""

    def __init__(self) -> None:
        self._keys: dict[str, Ed25519PrivateKey] = {}

    def add(self, principal_id: str, key: Ed25519PrivateKey) -> str:
        self._keys[principal_id] = key
        return kid_for(key.public_key())

    def generate(self, principal_id: str) -> str:
        return self.add(principal_id, Ed25519PrivateKey.generate())

    def public_key(self, principal_id: str) -> Ed25519PublicKey | None:
        key = self._keys.get(principal_id)
        return key.public_key() if key is not None else None

    def private_key(self, principal_id: str) -> Ed25519PrivateKey | None:
        return self._keys.get(principal_id)

    def require_private(self, principal_id: str) -> Ed25519PrivateKey:
        key = self._keys.get(principal_id)
        if key is None:
            raise KeyError(principal_id)
        return key


class EphemeralPrincipalKeys(InMemoryPrincipalKeys):
    """For a ``:memory:`` gateway (demos, tests): every human gets a
    per-process key the first time something in this process signs for it,
    as the ephemeral gateway generates its own grant key. Nothing persists,
    so there is no real human to protect; a persistent gateway never uses it."""

    def private_key(self, principal_id: str) -> Ed25519PrivateKey | None:
        if principal_id not in self._keys:
            self.generate(principal_id)
        return self._keys[principal_id]


class FilePrincipalKeys:
    """``<dir>/<id>.pub`` (trusted) and ``<dir>/<id>.key`` (signing, 0600)."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def private_path(self, principal_id: str) -> Path:
        return self.directory / f"{_stem(principal_id)}.key"

    def public_path(self, principal_id: str) -> Path:
        return self.directory / f"{_stem(principal_id)}.pub"

    def public_key(self, principal_id: str) -> Ed25519PublicKey | None:
        try:
            path = self.public_path(principal_id)
            key = load_pem_public_key(path.read_bytes())
        except (OSError, ValueError):
            return None
        return key if isinstance(key, Ed25519PublicKey) else None

    def private_key(self, principal_id: str) -> Ed25519PrivateKey | None:
        try:
            path = self.private_path(principal_id)
            key = load_pem_private_key(path.read_bytes(), password=None)
        except (OSError, ValueError):
            return None
        return key if isinstance(key, Ed25519PrivateKey) else None

    def generate(self, principal_id: str) -> str:
        """Create ``<id>.key`` (0600) and ``<id>.pub``. Refuses to overwrite."""
        private_path = self.private_path(principal_id)
        if private_path.exists() or self.public_path(principal_id).exists():
            raise FileExistsError(f"a key for {principal_id} already exists in {self.directory}")
        ensure_private_dir(self.directory)
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        pub = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        # Private key first: a crash between the two leaves no trusted .pub
        # without its signing key.
        write_file_atomic(private_path, pem, private=True)
        write_file_atomic(self.public_path(principal_id), pub, private=False)
        return kid_for(key.public_key())

    def ensure(self, principal_id: str) -> str:
        """The principal's kid, generating its key pair if it has none."""
        public = self.public_key(principal_id)
        if public is not None:
            return kid_for(public)
        return self.generate(principal_id)
