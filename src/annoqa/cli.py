"""Command line: ``annoqa validate`` and ``annoqa report``.

Exit codes: 0 = clean, 1 = validation errors found, 2 = usage or input error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
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

    p_ts = sub.add_parser("traj-show", help="render trajectories with replayed observations for annotators")
    p_ts.add_argument("--items", type=Path, required=True)
    p_ts.add_argument("--out", type=Path, help="write the packet here instead of stdout")

    p_tc = sub.add_parser("traj-check", help="check trajectory labels against replay and the policy engine")
    p_tc.add_argument("--items", type=Path, required=True)
    p_tc.add_argument("--hidden", type=Path, help="hidden ground truth (final-answer faithfulness)")
    p_tc.add_argument("labels", type=Path, nargs="+")
    p_tc.add_argument("--gold", help="annotator id treated as reference")
    p_tc.add_argument("--out", type=Path, help="write the report here")

    p_rb = sub.add_parser("rubric-eval", help="lint rubrics and measure validity, hack resistance and reliability")
    p_rb.add_argument("--tasks", type=Path, required=True)
    p_rb.add_argument("--rubrics", type=Path, required=True)
    p_rb.add_argument("grades", type=Path, nargs="*")
    p_rb.add_argument("--reference", default="ref", help="grader whose marks produce the scores")
    p_rb.add_argument("--out", type=Path, help="write the report here")

    p_ss = sub.add_parser("step-show", help="render worked solutions for step-level annotation")
    p_ss.add_argument("--items", type=Path, required=True)
    p_ss.add_argument("--out", type=Path)
    p_sc = sub.add_parser("step-check", help="check step-level (process-reward) labels")
    p_sc.add_argument("--items", type=Path, required=True)
    p_sc.add_argument("--hidden", type=Path)
    p_sc.add_argument("labels", type=Path, nargs="+")
    p_sc.add_argument("--out", type=Path)

    p_ja = sub.add_parser("judge-audit", help="audit LLM judges against human gold with bias probes")
    p_ja.add_argument("--items", type=Path, required=True)
    p_ja.add_argument("--gold", type=Path, required=True, help="label file holding the human preferences")
    p_ja.add_argument("--gold-annotator", default="ref")
    p_ja.add_argument("--judge", action="append", default=[], help="reference judge name or cmd:<command>")
    p_ja.add_argument("--run", type=Path, action="append", default=[], help="recorded judge run (JSONL) to include")
    p_ja.add_argument("--record", type=Path, help="directory to save each judge's verdicts for reproducibility")
    p_ja.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "judge-audit":
        return _judge(args)
    if args.command in ("step-show", "step-check"):
        return _steps(args)
    if args.command == "rubric-eval":
        return _rubric(args)
    if args.command in ("traj-show", "traj-check"):
        return _traj(args)
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


def _traj(args: argparse.Namespace) -> int:
    from annoqa.trajeval import (
        build_traj_report,
        check,
        load_hidden,
        load_traj_labels,
        load_trajectories,
        render_packet,
    )

    try:
        trajs = load_trajectories(args.items)
        if args.command == "traj-show":
            packet = render_packet(trajs)
            if args.out:
                args.out.write_text(packet, encoding="utf-8")
                print(f"wrote {args.out}")
            else:
                print(packet)
            return 0
        hidden = load_hidden(args.hidden)
        labels = [lb for path in args.labels for lb in load_traj_labels(path)]
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = check(labels, trajs, hidden)
    for f in findings:
        print(f"{f.kind}: {f.where}: {f.code} [{f.annotator} / {f.trajectory_id}] {f.message}")
    if args.out:
        args.out.write_text(build_traj_report(labels, trajs, hidden, gold=args.gold), encoding="utf-8")
        print(f"wrote {args.out}")
    n_err = sum(f.kind == "error" for f in findings)
    print(f"{len(labels)} label(s): {n_err} error(s), {sum(f.kind == 'mismatch' for f in findings)} mismatch(es)")
    return 1 if n_err else 0


def _rubric(args: argparse.Namespace) -> int:
    from annoqa.rubrics import build_rubric_report, lint, load_grades, load_rubric_tasks, load_rubrics

    try:
        tasks = load_rubric_tasks(args.tasks)
        rubrics = load_rubrics(args.rubrics)
        grades = [g for path in args.grades for g in load_grades(path)]
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = [f for rb in rubrics for f in lint(rb)]
    for f in findings:
        print(f"{f.kind}: {f.task_id} {f.version} {f.criterion}: {f.code} {f.message}")
    if args.out:
        args.out.write_text(build_rubric_report(tasks, rubrics, grades, reference=args.reference), encoding="utf-8")
        print(f"wrote {args.out}")
    n_err = sum(f.kind == "error" for f in findings)
    print(f"{len(rubrics)} rubric(s): {n_err} lint error(s), {len(findings) - n_err} warning(s)")
    return 1 if n_err else 0


def _steps(args: argparse.Namespace) -> int:
    from annoqa.process import (
        build_step_report,
        check,
        load_solutions,
        load_step_hidden,
        load_step_labels,
        render_solutions,
    )

    try:
        sols = load_solutions(args.items)
        if args.command == "step-show":
            text = render_solutions(sols)
            if args.out:
                args.out.write_text(text, encoding="utf-8")
                print(f"wrote {args.out}")
            else:
                print(text)
            return 0
        hidden = load_step_hidden(args.hidden)
        labels = [lb for path in args.labels for lb in load_step_labels(path)]
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = check(labels, sols, hidden)
    for f in findings:
        print(f"{f.kind}: {f.where}: {f.code} [{f.annotator} / {f.solution_id}] {f.message}")
    if args.out:
        args.out.write_text(build_step_report(labels, sols, hidden), encoding="utf-8")
        print(f"wrote {args.out}")
    n_err = sum(f.kind == "error" for f in findings)
    print(f"{len(labels)} label(s): {n_err} error(s), {sum(f.kind == 'mismatch' for f in findings)} mismatch(es)")
    return 1 if n_err else 0


def _judge(args: argparse.Namespace) -> int:
    from annoqa.judgeaudit import (
        audit,
        build_judge_report,
        command_judge,
        gold_from_labels,
        load_run,
        make_probes,
        reference_judges,
        run_judge,
        save_run,
    )

    try:
        items = load_items(args.items)
        gold = gold_from_labels(load_labels(args.gold), args.gold_annotator)
    except (OSError, LoadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not gold:
        print(f"error: no labels from annotator {args.gold_annotator!r}", file=sys.stderr)
        return 2
    refs = reference_judges(gold)
    probes = make_probes(items, gold)
    results = []
    for spec in args.judge:
        if spec.startswith("cmd:"):
            judge, name = command_judge(spec[4:]), spec[4:]
        elif spec in refs:
            judge, name = refs[spec], spec
        else:
            print(
                f"error: unknown judge {spec!r} (reference judges: {', '.join(refs)}; or cmd:<command>)",
                file=sys.stderr,
            )
            return 2
        try:
            raw = run_judge(judge, probes)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"error: judge {name!r} failed: {exc}", file=sys.stderr)
            return 2
        if args.record:
            args.record.mkdir(parents=True, exist_ok=True)
            save_run(args.record / (re.sub(r"[^A-Za-z0-9_.-]+", "_", name) + ".jsonl"), name, raw)
        results.append(audit(name, raw, gold))
    for path in args.run:
        name, raw = load_run(path)
        results.append(audit(name, raw, gold))
    report = build_judge_report(results, items, gold)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
