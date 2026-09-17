"""Gate a built distribution before it can be published.

Usage: python scripts/check_dist.py [--version X.Y.Z] [dist]

Standard library only (it runs with `uv run --no-project` in the publish
workflow). Exits non-zero unless `dist` holds exactly one wheel and one
sdist for the expected version whose metadata says MIT, whose contents are
the eleven intended packages plus LICENSE/py.typed, and which carry no
secrets, local paths, tests, caches or private dependency references.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGES = {
    "atp_core",
    "atp_identity",
    "atp_policy",
    "atp_audit",
    "atp_evals",
    "atp_gateway",
    "atp_adapter_http",
    "atp_adapter_mcp",
    "atp_cli",
    "finance_agent",
    "notes_mcp_server",
}
FORBIDDEN_NAME_PARTS = (
    ".env",
    "keys.env",
    ".db",
    "/.atp/",
    "/tests/",
    "__pycache__",
    "node_modules",
    "/.git/",
    ".pyc",
    "eval-reports",
    "scratchpad",
    ".pem",
    ".key",
)
SECRET_PATTERNS = [
    re.compile(rb"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"(?i)ghp_[A-Za-z0-9]{36}|pypi-AgEIcHlwaS5vcmc"),
    re.compile(rb"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9_.-]+"),
    re.compile(rb"/home/[a-z0-9_.-]+/|/Users/[A-Za-z0-9_.-]+/"),
]
PRIVATE_DEP = re.compile(r"(?i)@\s*(file:|git\+|https?://)|localhost|127\.0\.0\.1|[A-Za-z]:\\")


def fail(msg: str) -> None:
    print(f"check_dist: FAIL: {msg}")
    sys.exit(1)


def scan_bytes(name: str, data: bytes) -> list[str]:
    hits = []
    for pat in SECRET_PATTERNS:
        m = pat.search(data)
        if m:
            hits.append(f"{name}: {m.group(0)[:60]!r}")
    return hits


def check_metadata(meta: str, version: str) -> None:
    def field(key: str) -> list[str]:
        return [line[len(key) + 2 :] for line in meta.splitlines() if line.startswith(key + ": ")]

    if field("Name") != ["agent-trust-plane"]:
        fail(f"Name is {field('Name')}")
    if field("Version") != [version]:
        fail(f"Version is {field('Version')}, expected {version}")
    if field("License-Expression") != ["MIT"]:
        fail(f"License-Expression is {field('License-Expression')}")
    if "LICENSE" not in field("License-File"):
        fail("License-File LICENSE missing")
    if field("Requires-Python") != [">=3.12"]:
        fail(f"Requires-Python is {field('Requires-Python')}")
    for key in ("Project-URL", "Keywords", "Classifier", "Summary"):
        if not field(key):
            fail(f"no {key} in METADATA")
    for dep in field("Requires-Dist"):
        if PRIVATE_DEP.search(dep):
            fail(f"non-index dependency: {dep}")
    # The long description must not rely on pypi.org resolving relative paths.
    body = meta.split("\n\n", 1)[1] if "\n\n" in meta else ""
    rel = [
        m
        for m in re.findall(r"\]\(([^)]+)\)", body)
        if not m.startswith(("http://", "https://", "#"))
    ]
    if rel:
        fail(f"relative links in long description: {rel[:5]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", nargs="?", default="dist")
    parser.add_argument("--version", default=None)
    args = parser.parse_args()
    version = args.version
    if version is None:
        version = tomllib.load((ROOT / "pyproject.toml").open("rb"))["project"]["version"]
    dist = Path(args.dist)
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        fail(f"expected one wheel and one sdist, found {[p.name for p in wheels + sdists]}")
    whl, sdist = wheels[0], sdists[0]
    if whl.name != f"agent_trust_plane-{version}-py3-none-any.whl":
        fail(f"wheel name {whl.name} does not match version {version}")
    if sdist.name != f"agent_trust_plane-{version}.tar.gz":
        fail(f"sdist name {sdist.name} does not match version {version}")

    hits: list[str] = []
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
        info = f"agent_trust_plane-{version}.dist-info"
        check_metadata(z.read(f"{info}/METADATA").decode("utf-8"), version)
        if f"{info}/licenses/LICENSE" not in names:
            fail("LICENSE not in the wheel")
        if "Copyright (c) 2026 George Gakravyi" not in z.read(f"{info}/licenses/LICENSE").decode(
            "utf-8"
        ):
            fail("LICENSE copyright line missing")
        ep = z.read(f"{info}/entry_points.txt").decode("utf-8")
        for script in ("atp", "agent-trust-plane"):
            if f"{script} = atp_cli.main:main" not in ep:
                fail(f"console script {script} missing")
        tops = {n.split("/", 1)[0] for n in names if "/" in n and not n.startswith(info)}
        if tops != EXPECTED_PACKAGES:
            fail(f"unexpected top-level wheel contents: {sorted(tops ^ EXPECTED_PACKAGES)}")
        bad = [n for n in names if any(x in n.lower() for x in FORBIDDEN_NAME_PARTS)]
        if bad:
            fail(f"unintended files in wheel: {bad}")
        missing_typed = [p for p in EXPECTED_PACKAGES if f"{p}/py.typed" not in names]
        if missing_typed:
            fail(f"py.typed missing for {missing_typed}")
        for n in names:
            if n.endswith((".py", ".txt", ".md", ".yaml", ".json", ".toml")):
                hits += scan_bytes(f"wheel:{n}", z.read(n))

    with tarfile.open(sdist, "r:gz") as t:
        members = t.getmembers()
        snames = [m.name for m in members]
        prefix = f"agent_trust_plane-{version}/"
        if not all(n.startswith(prefix) for n in snames):
            fail("sdist entries outside the versioned root")
        for required in ("pyproject.toml", "LICENSE", "README.md", "PKG-INFO"):
            if prefix + required not in snames:
                fail(f"{required} missing from sdist")
        check_metadata(t.extractfile(prefix + "PKG-INFO").read().decode("utf-8"), version)  # type: ignore[union-attr]
        bad = [n for n in snames if any(x in n.lower() for x in FORBIDDEN_NAME_PARTS)]
        if bad:
            fail(f"unintended files in sdist: {bad}")
        for m in members:
            if m.isfile() and m.name.endswith((".py", ".txt", ".md", ".yaml", ".json", ".toml")):
                hits += scan_bytes(f"sdist:{m.name}", t.extractfile(m).read())  # type: ignore[union-attr]

    if hits:
        fail("secret/local-path patterns found:\n  " + "\n  ".join(hits))
    print(f"check_dist: OK version {version} MIT")
    print(f"  {whl.name}: {len(names)} entries")
    print(f"  {sdist.name}: {len(snames)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
