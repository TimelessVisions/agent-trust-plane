"""Unit tests for the execution grant primitive."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from atp_core import GrantError, ReasonCode, canonical_json
from atp_gateway.grant_keys import (
    generate_grant_key,
    load_grant_keys,
    read_env_file,
    rotate_grant_key,
)
from atp_gateway.grants import (
    TOKEN_VERSION,
    GrantClaims,
    GrantSigner,
    GrantStatus,
    GrantStore,
    GrantVerifier,
    InMemoryGrantStore,
    SqliteGrantStore,
    kid_for,
    new_grant_claims,
)

from gateway_fixtures import NOW


def claims() -> GrantClaims:
    return new_grant_claims(
        trace_id="a" * 12,
        decision_id="dec_1",
        envelope_id="env_1",
        action_hash="f" * 64,
        agent_id="accounts-payable-agent",
        policy_set_version="payments-v2",
        ttl_seconds=120,
        now=NOW,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest) -> Iterator[GrantStore]:
    if request.param == "memory":
        yield InMemoryGrantStore()
    else:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        yield SqliteGrantStore(conn)
        conn.close()


def _signer() -> GrantSigner:
    key = Ed25519PrivateKey.generate()
    return GrantSigner(key, kid_for(key.public_key()))


def _verifier(*signers: GrantSigner) -> GrantVerifier:
    return GrantVerifier({s.kid: s.public_key for s in signers})


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TestSigner:
    def test_mint_verify_roundtrip(self) -> None:
        signer = _signer()
        c = claims()
        token = signer.mint(c)
        assert _verifier(signer).verify(token) == c
        header_b64, _claims_b64, sig_b64 = token.split(".")
        header = json.loads(_b64d(header_b64))
        assert header == {"alg": "EdDSA", "kid": signer.kid, "v": TOKEN_VERSION}
        assert TOKEN_VERSION == "atp-grant/2"
        assert len(_b64d(sig_b64)) == 64
        # kid = sha256(raw public key)[:16]
        raw = signer.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        assert signer.kid == hashlib.sha256(raw).hexdigest()[:16]

    def test_wrong_key_is_rejected(self) -> None:
        """A token signed by a different key that claims the trusted kid."""
        real, attacker = _signer(), _signer()
        token = attacker.mint(claims())
        _, claims_b64, sig_b64 = token.split(".")
        header = _b64e(canonical_json({"alg": "EdDSA", "kid": real.kid, "v": TOKEN_VERSION}))
        with pytest.raises(GrantError) as exc:
            _verifier(real).verify(f"{header}.{claims_b64}.{sig_b64}")
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID

    def test_tampered_claims_rejected(self) -> None:
        signer = _signer()
        token = signer.mint(claims())
        header_b64, claims_b64, sig_b64 = token.split(".")
        body = json.loads(_b64d(claims_b64))
        body["expires_at"] = (NOW + timedelta(days=365)).isoformat()
        forged = _b64e(canonical_json(body))
        with pytest.raises(GrantError) as exc:
            _verifier(signer).verify(f"{header_b64}.{forged}.{sig_b64}")
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID

    def test_tampered_header_rejected(self) -> None:
        """The signature covers the header too: swapping the kid breaks it."""
        a, b = _signer(), _signer()
        token = a.mint(claims())
        _, claims_b64, sig_b64 = token.split(".")
        header = _b64e(canonical_json({"alg": "EdDSA", "kid": b.kid, "v": TOKEN_VERSION}))
        with pytest.raises(GrantError) as exc:
            _verifier(a, b).verify(f"{header}.{claims_b64}.{sig_b64}")
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID

    def test_unknown_kid_is_signature_invalid(self) -> None:
        signer, other = _signer(), _signer()
        token = signer.mint(claims())
        with pytest.raises(GrantError) as exc:
            _verifier(other).verify(token)
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID
        assert "kid" in exc.value.message

    def test_v1_hmac_token_rejected(self) -> None:
        """An ``atp-grant/1`` token (canonical claims "." HMAC-SHA256) is malformed now."""
        c = claims()
        v1_body = canonical_json({**c.model_dump(mode="json"), "v": "atp-grant/1"})
        v1_sig = hmac.new(b"k" * 32, v1_body, hashlib.sha256).digest()
        token = f"{_b64e(v1_body)}.{_b64e(v1_sig)}"
        with pytest.raises(GrantError) as exc:
            _verifier(_signer()).verify(token)
        assert exc.value.reason_code is ReasonCode.GRANT_MALFORMED
        assert "atp-grant/1" in exc.value.message

    @pytest.mark.parametrize(
        "header",
        [
            {"alg": "HS256", "kid": "x", "v": "atp-grant/2"},
            {"alg": "none", "kid": "x", "v": "atp-grant/2"},
            {"alg": "EdDSA", "kid": "x", "v": "atp-grant/1"},
            {"alg": "EdDSA", "v": "atp-grant/2"},
            {"alg": "EdDSA", "kid": "x", "v": "atp-grant/2", "jku": "https://evil"},
        ],
    )
    def test_header_must_be_exactly_eddsa_v2(self, header: dict[str, str]) -> None:
        signer = _signer()
        if "kid" in header:  # a trusted kid, so only the other header fields are wrong
            header = {**header, "kid": signer.kid}
        _, claims_b64, sig_b64 = signer.mint(claims()).split(".")
        with pytest.raises(GrantError) as exc:
            _verifier(signer).verify(f"{_b64e(canonical_json(header))}.{claims_b64}.{sig_b64}")
        assert exc.value.reason_code is ReasonCode.GRANT_MALFORMED

    def test_non_canonical_base64_rejected(self) -> None:
        signer = _signer()
        token = signer.mint(claims())
        with pytest.raises(GrantError) as exc:
            _verifier(signer).verify(token + "!")
        assert exc.value.reason_code is ReasonCode.GRANT_MALFORMED

    @pytest.mark.parametrize("token", ["", "garbage", "a.b", "a.b.c", "not-base64!.x", "a.b.c.d"])
    def test_malformed_tokens(self, token: str) -> None:
        with pytest.raises(GrantError) as exc:
            _verifier(_signer()).verify(token)
        assert exc.value.reason_code in {
            ReasonCode.GRANT_MALFORMED,
            ReasonCode.GRANT_SIGNATURE_INVALID,
        }

    def test_signer_refuses_a_kid_that_is_not_its_key(self) -> None:
        """Replaces the HMAC short-key check: the signer validates its key material."""
        key = Ed25519PrivateKey.generate()
        with pytest.raises(ValueError):
            GrantSigner(key, "0" * 16)

    def test_retired_kid_stops_verifying_after_its_deadline(self) -> None:
        old = _signer()
        token = old.mint(claims())
        now = [NOW]
        verifier = GrantVerifier(
            {old.kid: old.public_key},
            not_after={old.kid: NOW + timedelta(seconds=120)},
            clock=lambda: now[0],
        )
        assert verifier.verify(token).grant_id
        now[0] = NOW + timedelta(seconds=120)
        with pytest.raises(GrantError) as exc:
            verifier.verify(token)
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID


class TestKeyStorageAndRotation:
    def test_generated_key_files(self, tmp_path: Path) -> None:
        kid = generate_grant_key(tmp_path / "keys")
        key = tmp_path / "keys" / f"grant-{kid}.key"
        pub = tmp_path / "keys" / f"grant-{kid}.pub"
        assert key.read_text(encoding="ascii").startswith("-----BEGIN PRIVATE KEY-----")
        assert pub.read_text(encoding="ascii").startswith("-----BEGIN PUBLIC KEY-----")
        if os.name != "nt":
            assert (key.stat().st_mode & 0o077) == 0
        ring = load_grant_keys(tmp_path / "keys", kid, grant_ttl_seconds=120, now=NOW)
        assert ring.signer.kid == kid
        c = claims()
        assert ring.verifier.verify(ring.signer.mint(c), now=NOW) == c

    def test_key_file_must_match_its_kid(self, tmp_path: Path) -> None:
        keys = tmp_path / "keys"
        a = generate_grant_key(keys)
        b = generate_grant_key(keys)
        (keys / f"grant-{a}.key").write_bytes((keys / f"grant-{b}.key").read_bytes())
        with pytest.raises(ValueError, match="kid"):
            load_grant_keys(keys, a, grant_ttl_seconds=120, now=NOW)

    def test_old_kid_verifies_after_rotation(self, tmp_path: Path) -> None:
        """Review Focus 2: a grant minted under the old kid verifies until it
        expires after `atp keygen --rotate`; then the old key is gone."""
        keys = tmp_path / "keys"
        env = tmp_path / "keys.env"
        old = generate_grant_key(keys)
        env.write_text(f"ATP_OPERATOR_KEY=x\nATP_GRANT_SIGNING_KID={old}\n", encoding="utf-8")
        before = load_grant_keys(keys, old, grant_ttl_seconds=120, now=NOW)
        c = claims()  # issued at NOW, expires at NOW + 120 s
        token = before.signer.mint(c)

        rotated_at = NOW + timedelta(seconds=30)
        prev, new = rotate_grant_key(keys, env, now=rotated_at)
        assert prev == old and new != old
        assert read_env_file(env)["ATP_GRANT_SIGNING_KID"] == new
        assert read_env_file(env)["ATP_OPERATOR_KEY"] == "x"
        assert not (keys / f"grant-{old}.key").exists()  # the old key can no longer sign
        assert (keys / f"grant-{old}.pub").exists()

        after = load_grant_keys(keys, new, grant_ttl_seconds=120, now=rotated_at)
        assert after.signer.kid == new
        assert after.verifier.verify(token, now=rotated_at) == c  # old kid still verifies
        new_token = after.signer.mint(claims())
        assert after.verifier.verify(new_token, now=rotated_at).grant_id
        # The same in-memory verifier drops the old kid on schedule.
        with pytest.raises(GrantError) as exc:
            after.verifier.verify(token, now=rotated_at + timedelta(seconds=120))
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID

        # One grant_ttl after the rotation the old public key is no longer trusted.
        later = load_grant_keys(
            keys, new, grant_ttl_seconds=120, now=rotated_at + timedelta(seconds=120)
        )
        with pytest.raises(GrantError) as exc:
            later.verifier.verify(token, now=rotated_at + timedelta(seconds=120))
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID

    def test_rotation_crash_before_env_switch_strands_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The .retired marker is written before keys.env switches: a crash in
        between leaves the old key active and usable, and a crash after the
        switch can never leave the old .pub unmarked (untrusted)."""
        import atp_gateway.grant_keys as gk

        keys = tmp_path / "keys"
        env = tmp_path / "keys.env"
        old = generate_grant_key(keys)
        env.write_text(f"ATP_GRANT_SIGNING_KID={old}\n", encoding="utf-8")
        token = load_grant_keys(keys, old, grant_ttl_seconds=120, now=NOW).signer.mint(claims())

        def crash(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(gk, "update_env_file", crash)
        with pytest.raises(OSError):
            rotate_grant_key(keys, env, now=NOW)
        assert (keys / f"grant-{old}.retired").exists()  # marked before the switch
        assert read_env_file(env)["ATP_GRANT_SIGNING_KID"] == old
        ring = load_grant_keys(keys, old, grant_ttl_seconds=120, now=NOW)
        assert ring.verifier.verify(ring.signer.mint(claims()), now=NOW).grant_id
        monkeypatch.undo()

        later = NOW + timedelta(seconds=60)
        _, new = rotate_grant_key(keys, env, now=later)  # the re-run completes
        after = load_grant_keys(keys, new, grant_ttl_seconds=120, now=later)
        assert after.verifier.verify(token, now=later).grant_id
        assert after.retired[old] == later + timedelta(seconds=120)  # re-run's time

    def test_future_retired_time_is_a_config_error(self, tmp_path: Path) -> None:
        keys = tmp_path / "keys"
        active = generate_grant_key(keys)
        old = generate_grant_key(keys)
        marker = keys / f"grant-{old}.retired"
        marker.write_text((NOW + timedelta(minutes=4)).isoformat(), encoding="ascii")
        assert old in load_grant_keys(keys, active, grant_ttl_seconds=120, now=NOW).retired
        marker.write_text((NOW + timedelta(hours=1)).isoformat(), encoding="ascii")
        with pytest.raises(ValueError, match="future"):
            load_grant_keys(keys, active, grant_ttl_seconds=120, now=NOW)

    def test_unretired_stray_public_key_is_not_trusted(self, tmp_path: Path) -> None:
        keys = tmp_path / "keys"
        active = generate_grant_key(keys)
        stray = generate_grant_key(keys)
        stray_ring = load_grant_keys(keys, stray, grant_ttl_seconds=120, now=NOW)
        token = stray_ring.signer.mint(claims())
        ring = load_grant_keys(keys, active, grant_ttl_seconds=120, now=NOW)
        with pytest.raises(GrantError) as exc:
            ring.verifier.verify(token)
        assert exc.value.reason_code is ReasonCode.GRANT_SIGNATURE_INVALID


class TestStore:
    def test_single_use(self, store: GrantStore) -> None:
        c = claims()
        store.issue(c)
        first = store.consume(c.grant_id, NOW)
        assert first.status is GrantStatus.CONSUMED
        with pytest.raises(GrantError) as exc:
            store.consume(c.grant_id, NOW)
        assert exc.value.reason_code is ReasonCode.GRANT_ALREADY_CONSUMED

    def test_unknown_grant(self, store: GrantStore) -> None:
        with pytest.raises(GrantError) as exc:
            store.consume("xg_nope", NOW)
        assert exc.value.reason_code is ReasonCode.GRANT_NOT_FOUND

    def test_revoked_grant(self, store: GrantStore) -> None:
        c = claims()
        store.issue(c)
        store.revoke(c.grant_id)
        with pytest.raises(GrantError) as exc:
            store.consume(c.grant_id, NOW)
        assert exc.value.reason_code is ReasonCode.GRANT_REVOKED


def test_sqlite_store_reads_a_row_written_by_0_3(tmp_path: Path) -> None:
    """0.3.x stored claims with ``v: atp-grant/1``; the version now lives in the
    token header, so an old row still loads (e.g. for a late outcome report)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = SqliteGrantStore(conn)
    c = claims()
    old = json.dumps({**c.model_dump(mode="json"), "v": "atp-grant/1"})
    conn.execute(
        "INSERT INTO execution_grants (grant_id, status, claims) VALUES (?, ?, ?)",
        (c.grant_id, "issued", old),
    )
    record = store.get(c.grant_id)
    assert record is not None and record.claims == c
    conn.close()
