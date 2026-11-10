"""Review Focus 1: a real 0.3.2 home upgrades to the current atp.

The fixture under ``fixtures/home-0.3.2`` was written by agent-trust-plane
0.3.2 itself (``scripts/make_032_fixture.py``): ``atp demo wrap`` plus a
0.3.2 ``atp evidence export`` of every trace. It is copied into ``tmp_path``
first and never mutated. ``dot-atp`` is the home's ``.atp`` (renamed so git
keeps it). The CLI runs as a subprocess, as a person would run it.

What 0.3.2 actually wrote: an HMAC ``ATP_GRANT_SIGNING_KEY`` in keys.env,
unsigned root delegations, and an ``atp-mcp.yaml`` without ``version:``.
Its ``policies.yaml`` and regression suite already carried ``version: 1``.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from atp_identity import SqliteDelegationStore

FIXTURE = Path(__file__).parent / "fixtures" / "home-0.3.2"
BIN = Path(sys.executable).parent
ATP = str(BIN / ("atp.exe" if os.name == "nt" else "atp"))


def _materialize(dest: Path) -> Path:
    work = dest / "proj"
    shutil.copytree(FIXTURE, work)
    (work / "dot-atp").rename(work / ".atp")
    (work / ".atp" / "dot-gitignore").rename(work / ".atp" / ".gitignore")
    if os.name != "nt":
        (work / ".atp" / "keys.env").chmod(0o600)
    # The generator stripped the 0.3.2 venv's interpreter path; point the
    # upstream back at an interpreter that can run notes_mcp_server.
    cfg = work / "atp-mcp.yaml"
    text = cfg.read_text(encoding="utf-8")
    assert "  command: python3\n" in text
    cfg.write_text(
        text.replace("  command: python3\n", f"  command: {json.dumps(sys.executable)}\n"),
        encoding="utf-8",
    )
    return work


def _atp(cwd: Path, *args: str, stdin: str | None = "") -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATP_")}
    env["PATH"] = str(BIN) + os.pathsep + env.get("PATH", "")
    env["PYTHONWARNINGS"] = ""
    return subprocess.run(
        [ATP, *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _warnings(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("warning:")]


def _env(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _roots(db: Path) -> list[tuple[str, bool]]:
    conn = sqlite3.connect(str(db))
    try:
        return [
            (g.grant_id, g.signature is not None)
            for g in SqliteDelegationStore(conn).all()
            if g.is_root
        ]
    finally:
        conn.close()


def test_032_home_upgrades(tmp_path: Path) -> None:
    before = {p.relative_to(FIXTURE): p.read_bytes() for p in FIXTURE.rglob("*") if p.is_file()}
    work = _materialize(tmp_path)
    home = work / ".atp"
    manifest = json.loads((FIXTURE / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["package"] == "agent-trust-plane==0.3.2"
    traces = manifest["traces"]
    assert traces

    # The 0.3.2 state this test is about.
    old_keys = _env(home / "keys.env")
    assert "ATP_GRANT_SIGNING_KEY" in old_keys and "ATP_GRANT_SIGNING_KID" not in old_keys
    old_roots = _roots(home / "atp.db")
    assert old_roots and not any(signed for _, signed in old_roots)
    assert "version" not in (work / "atp-mcp.yaml").read_text(encoding="utf-8").split("\n")[0]

    # 1. It starts: offline commands read the old store.
    listed = _atp(work, "trace", "list", "--json")
    assert listed.returncode == 0, listed.stderr
    assert sorted(t["trace_id"] for t in json.loads(listed.stdout)) == sorted(traces)
    assert _warnings(listed.stderr) == []

    # 2. `atp mcp wrap` starts the home from atp-mcp.yaml (stdin closed: the
    #    session ends at once) and warns exactly once, for the one unversioned file.
    wrap = _atp(work, "mcp", "wrap", "--config", "atp-mcp.yaml")
    assert wrap.returncode == 0, wrap.stderr
    warned = _warnings(wrap.stderr)
    assert len(warned) == 1, wrap.stderr
    assert "atp-mcp.yaml" in warned[0] and "atp migrate" in warned[0]
    assert "atp mcp wrap: notes [ENFORCE]" in wrap.stderr

    # 3. The HMAC key became an Ed25519 key; the operator key is kept.
    new_keys = _env(home / "keys.env")
    assert "ATP_GRANT_SIGNING_KEY" not in new_keys
    assert old_keys["ATP_GRANT_SIGNING_KEY"] not in (home / "keys.env").read_text(encoding="utf-8")
    assert new_keys["ATP_OPERATOR_KEY"] == old_keys["ATP_OPERATOR_KEY"]
    kid = new_keys["ATP_GRANT_SIGNING_KID"]
    assert (home / "keys" / f"grant-{kid}.key").is_file()
    assert (home / "keys" / f"grant-{kid}.pub").is_file()

    # 4. C5's one-shot migration signed the 0.3.2 unsigned roots, ids kept.
    after = dict(_roots(home / "atp.db"))
    for grant_id, _ in old_roots:
        assert after[grant_id] is True, grant_id
    marker = home / "principals" / ".roots-migrated"
    assert marker.read_text(encoding="utf-8") == f"signed {len(old_roots)}\n"

    # 5. `atp migrate` makes the files current; a second run changes nothing.
    files = ["atp-mcp.yaml", ".atp/policies.yaml", "atp-regression.yaml"]
    mig = _atp(work, "migrate", *files)
    assert mig.returncode == 0, mig.stderr
    assert "migrated atp-mcp.yaml (mcp-config): added version: 1" in mig.stdout
    assert mig.stdout.count("already version 1") == 2
    again = _atp(work, "migrate", *files)
    assert again.returncode == 0 and again.stdout.count("already version 1") == 3
    rewrap = _atp(work, "mcp", "wrap", "--config", "atp-mcp.yaml")
    assert rewrap.returncode == 0, rewrap.stderr
    assert _warnings(rewrap.stderr) == []

    # 6. Old traces still verify: the 0.3.2 bundles verify, and a bundle the
    #    current code exports from the migrated store has the same hash chain.
    for tid in traces:
        old_bundle = work / "evidence" / f"{tid}.json"
        res = _atp(work, "evidence", "verify", str(old_bundle))
        assert res.returncode == 0 and res.stdout.startswith("OK"), res.stdout + res.stderr
        new_bundle = tmp_path / f"{tid}.new.json"
        res = _atp(work, "evidence", "export", tid, "--out", str(new_bundle))
        assert res.returncode == 0, res.stderr
        res = _atp(work, "evidence", "verify", str(new_bundle))
        assert res.returncode == 0 and res.stdout.startswith("OK"), res.stdout + res.stderr
        old = json.loads(old_bundle.read_text(encoding="utf-8"))
        new = json.loads(new_bundle.read_text(encoding="utf-8"))
        hashes = [(e["seq"], e["prev_hash"], e["hash"]) for e in old["events"]]
        assert [(e["seq"], e["prev_hash"], e["hash"]) for e in new["events"]][: len(hashes)] == (
            hashes
        )

    # 7. The 0.3.2 regression suite still passes.
    test = _atp(work, "test", "atp-regression.yaml")
    assert test.returncode == 0, test.stdout + test.stderr
    assert "1/1 passed" in test.stdout
    assert _warnings(test.stderr) == []

    # The committed fixture was not touched.
    assert {
        p.relative_to(FIXTURE): p.read_bytes() for p in FIXTURE.rglob("*") if p.is_file()
    } == before
