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
    key = home.principals_dir / f"{LOCAL_HUMAN}.key"
    pub = home.principals_dir / f"{LOCAL_HUMAN}.pub"
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
    assert (home.principals_dir / "alice.key").exists()


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
    assert (home / "principals" / "carol.key").exists()
    assert _private(home / "principals" / "carol.key")
    assert "PRIVATE" not in r.stdout
    again = subprocess.run(
        [sys.executable, "-m", "atp_cli.main", "principal", "keygen", "carol", "--home", str(home)],
        capture_output=True,
        text=True,
    )
    assert again.returncode == 2 and "exists" in again.stderr
