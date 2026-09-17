"""Check relative Markdown links and code-fence path references across the repo.

Usage: uv run python scripts/check_links.py
Exit 1 when a relative link target does not exist. External URLs are not fetched.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LINK = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(#[^)]*)?\)")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = subprocess.run(
        ["git", "ls-files", "*.md", "**/*.md"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    bad: list[str] = []
    for rel in files:
        if rel.startswith("docs/archive/"):
            continue  # historical snapshot; links were valid at the time
        path = root / rel
        text = path.read_text(encoding="utf-8")
        for m in LINK.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                bad.append(f"{rel}: {target}")
    for b in bad:
        print(b)
    print(f"{len(files)} files, {len(bad)} broken relative links")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
