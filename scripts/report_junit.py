"""Report GitHub Actions pytest JUnit outcomes without treating missing work as green.

Used by the release-branch verification workflow. This is a *reporting and gating* tool:
it never reclassifies failures, errors, skips, or absent test runs as PASS.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def _summary(message: str) -> None:
    print(message, flush=True)
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")


def inspect_junit(
    xml_path: Path, *, label: str, min_tests: int, max_skips: int, required_cases: list[str]
) -> bool:
    if not xml_path.is_file():
        _summary(f"### {label}: NOT_MEASURED\nJUnit file missing: `{xml_path}`.")
        return False

    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as exc:
        _summary(f"### {label}: INCONCLUSIVE\nUnreadable JUnit file: {type(exc).__name__}: {exc}.")
        return False

    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if not suites:
        _summary(f"### {label}: INCONCLUSIVE\nNo JUnit testsuite elements were found.")
        return False

    counts = {
        key: sum(int(s.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    cases = root.findall(".//testcase")
    executed_names = {c.get("name", "") for c in cases}
    skipped_cases = [
        f"{c.get('classname', '')}::{c.get('name', '')} — {c.find('skipped').get('message', '')}"
        for c in cases
        if c.find("skipped") is not None
    ]
    missing = [name for name in required_cases if name not in executed_names]

    failures = []
    if counts["tests"] < min_tests:
        failures.append(f"expected at least {min_tests} tests, got {counts['tests']}")
    if counts["failures"] or counts["errors"]:
        failures.append(f"{counts['failures']} failures and {counts['errors']} errors")
    if counts["skipped"] > max_skips:
        failures.append(f"{counts['skipped']} skips exceed the documented allowance {max_skips}")
    if missing:
        failures.append(f"required cases not collected: {missing}")
    if counts["tests"] != len(cases):
        failures.append(
            f"JUnit tests count {counts['tests']} does not match testcase entries {len(cases)}"
        )

    state = "FAIL" if failures else "PASS"
    lines = [
        f"### {label}: {state}",
        f"JUnit: `{xml_path}`",
        f"tests={counts['tests']} failures={counts['failures']} "
        f"errors={counts['errors']} skipped={counts['skipped']}",
    ]
    if skipped_cases:
        lines.append("Skipped cases (explicit; **not** counted as tested):")
        lines.extend(f"- `{item}`" for item in skipped_cases)
    if failures:
        lines.extend(f"- {reason}" for reason in failures)
    _summary("\n".join(lines))
    return not failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--min-tests", type=int, default=1)
    parser.add_argument("--max-skips", type=int, default=0)
    parser.add_argument("--require-case", action="append", default=[])
    args = parser.parse_args()
    if args.min_tests < 1 or args.max_skips < 0:
        parser.error("--min-tests must be >= 1 and --max-skips must be >= 0")
    return (
        0
        if inspect_junit(
            args.xml,
            label=args.label,
            min_tests=args.min_tests,
            max_skips=args.max_skips,
            required_cases=args.require_case,
        )
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
