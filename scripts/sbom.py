"""Write a CycloneDX 1.5 JSON SBOM for the locked runtime dependency set.

Usage: uv run python scripts/sbom.py --out dist/sbom.cdx.json

The component list comes from `uv export` (the lockfile, runtime deps only).
An SBOM is an inventory, not a security property: it tells a reader what
was in the environment so advisories can be matched against it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else "0.0.0"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist/sbom.cdx.json")
    args = parser.parse_args()
    exported = subprocess.run(
        [
            "uv",
            "export",
            "--format",
            "requirements-txt",
            "--no-hashes",
            "--no-emit-project",
            "--no-dev",
            "--no-annotate",
            "--no-header",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    components = []
    for line in exported.splitlines():
        line = line.strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==([^\s;]+)", line)
        if not m:
            continue
        name, version = m.group(1).lower().replace("_", "-"), m.group(3)
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
            }
        )
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "type": "application",
                "name": "agent-trust-plane",
                "version": _project_version(),
                "purl": f"pkg:pypi/agent-trust-plane@{_project_version()}",
            },
        },
        "components": components,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bom, indent=2), encoding="utf-8")
    print(f"wrote {out}: {len(components)} components")
    return 0


if __name__ == "__main__":
    sys.exit(main())
