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

    p_code = sub.add_parser("code-check", help="check code-evaluation labels against hidden tests and write a report")
    p_code.add_argument("--items", type=Path, required=True)
    p_code.add_argument("labels", type=Path, nargs="+")
    p_code.add_argument("--gold", help="annotator id whose scores are the reference")
    p_code.add_argument("--out", type=Path, help="write the report here instead of stdout")

    p_fact = sub.add_parser("fact-check", help="check claim-level factuality labels against the sources and report")
    p_fact.add_argument("--items", type=Path, required=True)
    p_fact.add_argument("labels", type=Path, nargs="+")
    p_fact.add_argument("--gold", help="annotator id whose claims are the reference")
    p_fact.add_argument("--out", type=Path, help="write the report here")

    args = parser.parse_args(argv)
    if args.command == "code-check":
        return _code_check(args)
    if args.command == "fact-check":
        return _fact_check(args)
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


def _code_check(args: argparse.Namespace) -> int:
    from annoqa.codeeval import build_code_report, check, load_code_items, load_code_labels

    try:
        items = load_code_items(args.items)
        labels = [lb for path in args.labels for lb in load_code_labels(path)]
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = check(labels, items)
    for f in findings:
        print(f"{f.kind}: {f.where}: {f.code} [{f.annotator} / {f.item_id}] {f.message}")
    report = build_code_report(labels, items, gold=args.gold)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    n_err = sum(f.kind == "error" for f in findings)
    print(f"{len(labels)} label(s): {n_err} error(s), {sum(f.kind == 'mismatch' for f in findings)} mismatch(es)")
    return 1 if n_err else 0


def _fact_check(args: argparse.Namespace) -> int:
    from annoqa.factuality import build_fact_report, check, load_fact_items, load_fact_labels

    try:
        items = load_fact_items(args.items)
        labels = [lb for path in args.labels for lb in load_fact_labels(path)]
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = check(labels, items)
    for f in findings:
        print(f"{f.kind}: {f.where}: {f.code} [{f.annotator} / {f.item_id}] {f.message}")
    if args.out:
        args.out.write_text(build_fact_report(labels, items, gold=args.gold), encoding="utf-8")
        print(f"wrote {args.out}")
    n_err = sum(f.kind == "error" for f in findings)
    print(f"{len(labels)} label(s): {n_err} error(s), {len(findings) - n_err} warning(s)")
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
