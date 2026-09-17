"""Record the wrap demo: run it for real, keep the transcript, render an SVG.

    uv run python scripts/record_demo.py

Writes docs/demo/wrap-transcript.txt (the real stdout, temp paths replaced
by <tmp>) and docs/images/demo-wrap.svg (a static rendering of that
transcript). No typing animation, no edited output: what you see is what
`atp demo wrap` printed on the machine and date recorded in the header.
"""

from __future__ import annotations

import html
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_TXT = ROOT / "docs" / "demo" / "wrap-transcript.txt"
OUT_SVG = ROOT / "docs" / "images" / "demo-wrap.svg"

KEEP = [
    r"^DEMO D",
    r"^upstream:",
    r"^\d\. ",
    r"^  delegated capabilities",
    r"^  tools/list",
    r"^  write_note",
    r"^  delete_note",
    r"^\$ atp",
    r"^  (DENY|ALLOW|WOULD_DENY)  ",
    r"^  who:",
    r"^  authority:",
    r"^  action:",
    r"^  decided by:",
    r"^    \[FAIL\]",
    r"^  what would need to change",
    r"^    - ",
    r"^  ADDED",
    r"^    expected:",
    r"^  \[PASS\]",
    r"^  \d+/\d+ passed",
]


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "atp_cli.main", "demo", "wrap"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    text = proc.stdout
    text = re.sub(r"[A-Za-z]:\\[^\s'\"]*atp-wrap-demo-[^\s'\"\\]*", "<tmp>", text)
    text = re.sub(r"/[^\s'\"]*atp-wrap-demo-[^\s'\"/]*", "<tmp>", text)
    text = text.replace("'<tmp>\\", "'<tmp>/").replace("\\", "/")
    header = (
        f"# recorded {datetime.now(UTC).isoformat(timespec='seconds')} on "
        f"{platform.system()} {platform.release()}, Python {platform.python_version()}; "
        "real output of `uv run atp demo wrap`, temp paths replaced by <tmp>\n\n"
    )
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text(header + text, encoding="utf-8", newline="\n")

    lines = [ln for ln in text.splitlines() if any(re.match(k, ln) for k in KEEP)]
    lines = [re.sub(r"\s+--home\s+\S+", "", ln) for ln in lines]
    lines = [re.sub(r"\s+--suite\s+\S+", " --suite atp-regression.yaml", ln) for ln in lines]
    lines = [ln[:118] for ln in lines]
    width, line_h, pad = 960, 18, 16
    height = pad * 2 + line_h * (len(lines) + 1)
    rows = []
    for i, ln in enumerate(lines):
        y = pad + line_h * (i + 1)
        colour = "#c9d1d9"
        if ln.startswith("$ atp"):
            colour = "#7ee787"
        elif "DENY" in ln or "[FAIL]" in ln:
            colour = "#ff7b72"
        elif "ALLOW" in ln or "[PASS]" in ln or "passed" in ln:
            colour = "#3fb950"
        elif ln.startswith(("DEMO", "1.", "2.", "3.", "4.")):
            colour = "#79c0ff"
        rows.append(
            f'<text x="{pad}" y="{y}" fill="{colour}" xml:space="preserve">{html.escape(ln)}</text>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ui-monospace, SFMono-Regular, Menlo, '
        f'Consolas, monospace" font-size="13">\n'
        f'<rect width="{width}" height="{height}" rx="8" fill="#0d1117"/>\n'
        f'<text x="{pad}" y="{pad}" fill="#8b949e" font-size="11">uv run atp demo wrap  '
        f"(rendered from docs/demo/wrap-transcript.txt; real output, no animation)</text>\n"
        + "\n".join(rows)
        + "\n</svg>\n"
    )
    OUT_SVG.write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {OUT_TXT} ({len(text.splitlines())} lines) and {OUT_SVG} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
