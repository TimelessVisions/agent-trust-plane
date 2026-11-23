"""Command line: ``annoqa validate`` and ``annoqa report``.

Exit codes: 0 = clean, 1 = validation errors found, 2 = usage or input error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from annoqa.report import build_report
from annoqa.schema import Label, LoadError, load_items, load_labels
from annoqa.validate import validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="annoqa", description="Quality checks for pairwise-preference annotation.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="check label files against the schema and consistency rules")
    p_val.add_argument("--items", type=Path, required=True)
    p_val.add_argument("labels", type=Path, nargs="+")
    p_val.add_argument("--strict", action="store_true", help="treat warnings as failures too")

    p_rep = sub.add_parser("report", help="agreement, gold accuracy and adjudication queue as Markdown")
    p_rep.add_argument("--items", type=Path, required=True)
    p_rep.add_argument("labels", type=Path, nargs="+")
    p_rep.add_argument("--gold", help="annotator id whose labels are the reference")
    p_rep.add_argument("--out", type=Path, help="write the report here instead of stdout")

    args = parser.parse_args(argv)
    try:
        items = load_items(args.items)
        labels: list[Label] = []
        for path in args.labels:
            labels += load_labels(path)
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        findings = validate(labels, items)
        for f in findings:
            print(f"{f.severity}: {f}")
        n_err = sum(f.severity == "error" for f in findings)
        n_warn = len(findings) - n_err
        print(f"{len(labels)} label(s): {n_err} error(s), {n_warn} warning(s)")
        return 1 if n_err or (args.strict and n_warn) else 0

    report = build_report(labels, items, gold=args.gold)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
