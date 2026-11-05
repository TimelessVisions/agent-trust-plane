"""C5 in local mode: the ATP home holds the local human's key and signs
local root grants, so ``atp mcp wrap`` needs no extra step."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from atp_core import PrincipalKind, PrincipalRef, utcnow
from atp_gateway import build_runtime
from atp_identity import DelegationGrant, SqliteDelegationStore


def _private(path: Path) -> bool:
    return os.name == "nt" or (path.stat().st_mode & 0o077) == 0


def test_local_home_autosigns_local_human(tmp_path: Path) -> None:
    from atp_adapter_http import TrustPlaneClient
    from atp_cli.home import LOCAL_HUMAN, AtpHome
    from atp_gateway import create_app

    home = AtpHome(tmp_path / "h").ensure()
    key = home.principal_keys().private_path(LOCAL_HUMAN)
    pub = home.principal_keys().public_path(LOCAL_HUMAN)
    assert key.exists() and pub.exists()
    assert _private(key)
    assert "principals/" in (home.path / ".gitignore").read_text(encoding="utf-8").splitlines()
    before = key.read_bytes()
    home.ensure()  # idempotent: the key is never replaced
    assert key.read_bytes() == before

    settings = home.settings()
    rt = build_runtime(settings)
    try:
        app = create_app(settings, runtime=rt)
        human = {"id": LOCAL_HUMAN, "kind": "human"}
        with TrustPlaneClient.for_app(app, operator_key=rt.operator_key) as operator:
            root = operator.issue_delegation(
                {
                    "label": "local authority",
                    "grantor": human,
                    "grantee": human,
                    "capabilities": ["notes:read"],
                    "resource_scope": ["note:*"],
                    "expires_at": (utcnow() + timedelta(hours=1)).isoformat(),
                }
            )
        assert root["signature"] and root["signer_kid"]
        chain = rt.trust_plane.resolve_delegation(root["grant_id"])
        assert chain.root.signature == root["signature"]
    finally:
        rt.close()


def test_wrap_principal_gets_its_own_key(tmp_path: Path) -> None:
    from atp_cli.home import AtpHome

    home = AtpHome(tmp_path / "h").ensure(human="alice")
    assert home.principal_keys().private_path("alice").exists()


def test_home_resigns_unsigned_roots_from_032(tmp_path: Path) -> None:
    """Ruling: a 0.3.2 home's database holds unsigned roots. ``ensure()`` signs
    every unsigned root whose human grantor has a private key in the home (the
    local human always does), in place: same grant id, same content, so old
    chains and traces keep resolving and verifying."""
    from atp_cli.home import LOCAL_HUMAN, AtpHome

    path = tmp_path / "h"
    path.mkdir()
    conn = sqlite3.connect(path / "atp.db")
    store = SqliteDelegationStore(conn)
    local = PrincipalRef(id=LOCAL_HUMAN, kind=PrincipalKind.HUMAN)
    stranger = PrincipalRef(id="someone-else", kind=PrincipalKind.HUMAN)
    now = utcnow()
    grants = [
        DelegationGrant(
            label=f"0.3.2 root of {who.id}",
            grantor=who,
            grantee=who,
            capabilities=frozenset({"notes:read"}),
            resource_scope=("note:*",),
            issued_at=now,
            expires_at=now + timedelta(days=1),
        )
        for who in (local, stranger)
    ]
    for g in grants:
        store.put(g)
    conn.close()

    home = AtpHome(path).ensure()
    rt = build_runtime(home.settings())
    try:
        mine = rt.trust_plane.resolve_delegation(grants[0].grant_id)
        assert mine.root.signature and mine.root.label == grants[0].label
        from atp_core import DelegationError, ReasonCode

        with pytest.raises(DelegationError) as exc:
            rt.trust_plane.resolve_delegation(grants[1].grant_id)
        assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_UNSIGNED
    finally:
        rt.close()


def test_principal_keygen_cli(tmp_path: Path) -> None:
    home = tmp_path / "h"
    r = subprocess.run(
        [sys.executable, "-m", "atp_cli.main", "principal", "keygen", "carol", "--home", str(home)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    from atp_identity import FilePrincipalKeys

    carol = FilePrincipalKeys(home / "principals").private_path("carol")
    assert carol.exists()
    assert _private(carol)
    assert "PRIVATE" not in r.stdout
    again = subprocess.run(
        [sys.executable, "-m", "atp_cli.main", "principal", "keygen", "carol", "--home", str(home)],
        capture_output=True,
        text=True,
    )
    assert again.returncode == 2 and "exists" in again.stderr


def _plant_unsigned_root(db: Path, human: str) -> DelegationGrant:
    conn = sqlite3.connect(db)
    try:
        who = PrincipalRef(id=human, kind=PrincipalKind.HUMAN)
        now = utcnow()
        grant = DelegationGrant(
            label="planted",
            grantor=who,
            grantee=who,
            capabilities=frozenset({"notes:read"}),
            resource_scope=("note:*",),
            issued_at=now,
            expires_at=now + timedelta(days=1),
        )
        SqliteDelegationStore(conn).put(grant)
        conn.commit()
        return grant
    finally:
        conn.close()


def _assert_stays_unsigned(home_path: Path, grant: DelegationGrant) -> None:
    from atp_cli.home import AtpHome
    from atp_core import DelegationError, ReasonCode

    home = AtpHome(home_path).ensure()
    home.ensure()
    conn = sqlite3.connect(home.db_path)
    try:
        stored = SqliteDelegationStore(conn).get(grant.grant_id)
    finally:
        conn.close()
    assert stored is not None and stored.signature is None
    rt = build_runtime(home.settings())
    try:
        with pytest.raises(DelegationError) as exc:
            rt.trust_plane.resolve_delegation(grant.grant_id)
        assert exc.value.reason_code is ReasonCode.DELEGATION_ROOT_UNSIGNED
    finally:
        rt.close()


def test_root_planted_after_migration_stays_unsigned(tmp_path: Path) -> None:
    """The 0.3.x re-sign is a one-shot migration: once it has run, a root
    written into atp.db unsigned is never signed by a later ``ensure()``."""
    from atp_cli.home import LOCAL_HUMAN, AtpHome

    path = tmp_path / "h"
    path.mkdir()
    old = _plant_unsigned_root(path / "atp.db", LOCAL_HUMAN)
    AtpHome(path).ensure()  # the upgrade: signs the 0.3.2 root, records it
    planted = _plant_unsigned_root(path / "atp.db", LOCAL_HUMAN)
    _assert_stays_unsigned(path, planted)
    rt = build_runtime(AtpHome(path).settings())
    try:
        assert rt.trust_plane.resolve_delegation(old.grant_id).root.signature
    finally:
        rt.close()


def test_root_planted_in_fresh_home_stays_unsigned(tmp_path: Path) -> None:
    from atp_cli.home import LOCAL_HUMAN, AtpHome

    path = tmp_path / "h"
    AtpHome(path).ensure()  # a 1.0 home: nothing to migrate
    planted = _plant_unsigned_root(path / "atp.db", LOCAL_HUMAN)
    _assert_stays_unsigned(path, planted)
