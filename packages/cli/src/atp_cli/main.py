"""``atp`` — the Agent Trust Plane command line.

The loop:

  atp mcp wrap -- <mcp server command>      protect a server; decisions land in .atp/
  atp trace list                            see what was allowed / denied / WOULD_DENY
  atp policy explain TRACE                  why, and what would need to change
  atp regression add TRACE                  pin the decision as a CI test
  atp test atp-regression.yaml              run it (exit 1 on any changed decision)
  atp policy impact --from A --to B         what a policy change does to recorded actions
  atp mutate TRACE                          probe the policy around a recorded action, offline
  atp evidence export TRACE                 portable, hash-checked bundle for review

Exit codes: 0 ok · 1 a regression/impact check failed · 2 usage or input error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# --------------------------------------------------------------- helpers


class UsageError(Exception):
    """A user mistake: printed as one line, exit 2, never a traceback."""


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1 :]
    return argv, []


def _open_home(home_dir: str | None) -> Any:
    from atp_cli.home import AtpHome

    try:
        return AtpHome(home_dir).open()
    except (FileNotFoundError, RuntimeError) as exc:
        raise UsageError(str(exc)) from exc


def _trace_dict(runtime: Any, trace_id: str) -> dict[str, Any]:
    from atp_core import ATPError

    try:
        view = runtime.trust_plane.get_trace(trace_id)
    except ATPError as exc:
        raise UsageError(f"trace {trace_id}: {exc.message}") from exc
    body: dict[str, Any] = view.model_dump(mode="json")
    return body


def _suite_from_traces(runtime: Any, limit: int) -> Any:
    """Every convertible recorded decision in the local store, as one suite."""
    from atp_evals.regression import TraceConversionError, case_from_trace, merge_into_suite

    suite = None
    skipped = 0
    for summary in runtime.trust_plane.list_traces(limit):
        trace = _trace_dict(runtime, summary.trace_id)
        try:
            delegations, case = case_from_trace(trace, name=f"trace-{summary.trace_id}")
            suite = merge_into_suite(suite, delegations, case, suite_name="recorded actions")
        except (TraceConversionError, ValueError):
            skipped += 1
    if suite is None:
        raise UsageError("no convertible decisions in the local store")
    if skipped:
        _err(f"note: {skipped} trace(s) skipped (no resolved decision)")
    return suite


def _load_suite(path: str) -> Any:
    from atp_evals.regression import load_suite

    try:
        return load_suite(path)
    except (OSError, ValueError) as exc:
        raise UsageError(f"invalid suite {path}: {exc}") from exc


def _case(suite: Any, name: str) -> Any:
    case = next((c for c in suite.cases if c.name == name), None)
    if case is None:
        raise UsageError(f"no case named {name!r}; cases: {[c.name for c in suite.cases]}")
    return case


def _policy_file(args: argparse.Namespace) -> str | None:
    explicit = getattr(args, "policies", None)
    if explicit:
        if not Path(explicit).is_file():
            raise UsageError(f"policy file not found: {explicit}")
        return str(Path(explicit).resolve())
    from atp_cli.home import AtpHome

    home = AtpHome(getattr(args, "home", None))
    return str(home.policy_path) if home.policy_path.exists() else None


def _registry(policy_file: str | None) -> Any:
    from atp_policy import PolicySetRegistry

    try:
        return (
            PolicySetRegistry.with_file(policy_file) if policy_file else PolicySetRegistry.builtin()
        )
    except ValueError as exc:
        raise UsageError(f"invalid policy file: {exc}") from exc


# -------------------------------------------------------------- commands
def _cmd_doctor(args: argparse.Namespace) -> int:
    from atp_cli.doctor import format_doctor, run_doctor

    checks = run_doctor(port=args.port)
    print(format_doctor(checks))
    return 0 if all(c.ok for c in checks if c.name != "Node.js / npm (dashboard only)") else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    from atp_cli import demos

    if args.which == "injection":
        return demos.demo_injection()
    if args.which == "regression":
        return demos.demo_regression(Path(args.out) if args.out else None)
    if args.which == "wrap":
        return demos.demo_wrap(Path(args.out) if args.out else None)
    return demos.demo_mcp(Path(args.out) if args.out else None)


def _cmd_test(args: argparse.Namespace) -> int:
    from atp_evals.regression import format_text, run_suite, to_json, to_junit

    suite = _load_suite(args.suite)
    policy_file = args.policies or suite.policies or _policy_file(args)
    try:
        report = run_suite(suite, policy_set=args.policy_set, policy_file=policy_file)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    if args.json:
        Path(args.json).write_text(json.dumps(to_json(report), indent=2), encoding="utf-8")
    if args.junit:
        Path(args.junit).write_text(to_junit(report), encoding="utf-8")
    if not args.quiet:
        print(format_text(report))
    return 0 if report.ok else 1


def _add_case(
    trace: dict[str, Any],
    *,
    suite_path: Path,
    name: str | None,
    gateway: str | None,
    policy_file: str | None = None,
) -> int:
    from atp_evals.regression import (
        TraceConversionError,
        case_from_trace,
        dump_suite,
        load_suite,
        merge_into_suite,
    )

    existing = load_suite(suite_path) if suite_path.exists() else None
    try:
        delegations, case = case_from_trace(trace, name=name, gateway=gateway)
        suite = merge_into_suite(existing, delegations, case)
    except (TraceConversionError, ValueError) as exc:
        raise UsageError(f"trace could not be converted: {exc}") from exc
    if policy_file and suite.policies is None:
        rel = os.path.relpath(policy_file, suite_path.resolve().parent).replace("\\", "/")
        suite = suite.model_copy(update={"policies": rel})
    recorded_under = case.source.policy_set if case.source else None
    if recorded_under and suite.policy_set != recorded_under:
        if len(suite.cases) == 1:
            suite = suite.model_copy(update={"policy_set": recorded_under})
        else:
            _err(
                f"note: case recorded under {recorded_under}; the suite runs under "
                f"{suite.policy_set}"
            )
    dump_suite(suite, suite_path)
    print(
        f"ADDED {case.name}\n"
        f"  expected: {case.expect.outcome.value}"
        + (f" / {case.expect.reason_code}" if case.expect.reason_code else "")
        + (f" by {case.expect.matched_policy}" if case.expect.matched_policy else "")
        + f"\n  policy:   {case.source.policy_set if case.source else suite.policy_set}"
        f"\n  suite:    {suite_path} ({len(suite.cases)} case(s))"
        f"\n  run:      atp test {suite_path}"
    )
    print("the expectation is the decision the gateway made; review it before committing")
    return 0


def _cmd_regression_add(args: argparse.Namespace) -> int:
    runtime = _open_home(args.home)
    try:
        trace = _trace_dict(runtime, args.trace)
    finally:
        runtime.close()
    return _add_case(
        trace,
        suite_path=Path(args.suite),
        name=args.name,
        gateway=None,
        policy_file=_policy_file(args),
    )


def _cmd_record(args: argparse.Namespace) -> int:
    from atp_adapter_http import GatewayError, TrustPlaneClient

    key = args.operator_key or os.environ.get("ATP_OPERATOR_KEY")
    if not key:
        raise UsageError("record needs the operator key (--operator-key or $ATP_OPERATOR_KEY)")
    client = TrustPlaneClient(args.gateway, operator_key=key)
    try:
        trace = client.get_trace(args.trace)
    except GatewayError as exc:
        raise UsageError(f"could not fetch trace: {exc}") from exc
    return _add_case(trace, suite_path=Path(args.suite), name=args.name, gateway=args.gateway)


def _cmd_trace_list(args: argparse.Namespace) -> int:
    runtime = _open_home(args.home)
    try:
        rows = []
        for summary in runtime.trust_plane.list_traces(args.limit):
            view = runtime.trust_plane.get_trace(summary.trace_id)
            env, d = view.envelope, view.decision
            rows.append(
                {
                    "trace_id": summary.trace_id,
                    "at": summary.started_at.isoformat(timespec="seconds"),
                    "action": env.qualified_action if env else "-",
                    "resource": env.resource if env else "-",
                    "outcome": d.display_outcome if d else "-",
                    "reason": d.reason_code.value if d else "",
                    "last": summary.last_event_type.value,
                }
            )
    finally:
        runtime.close()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no traces recorded yet")
        return 0
    print(f"{'trace':<13}{'when (UTC)':<20}{'outcome':<24}{'action':<26}{'resource':<32}last event")
    for r in rows:
        when = r["at"].replace("T", " ")[:19]
        print(
            f"{r['trace_id']:<13}{when:<20}{r['outcome']:<24}{r['action'][:25]:<26}"
            f"{r['resource'][:31]:<32}{r['last']}"
            + (f"  {r['reason']}" if r["reason"] and r["outcome"] != "ALLOW" else "")
        )
    return 0


def _cmd_trace_show(args: argparse.Namespace) -> int:
    runtime = _open_home(args.home)
    try:
        trace = _trace_dict(runtime, args.trace)
    finally:
        runtime.close()
    if args.json:
        print(json.dumps(trace, indent=2))
        return 0
    print(
        f"trace {trace['trace_id']}  integrity: "
        f"{'valid' if trace['integrity']['valid'] else 'INVALID'}"
    )
    for e in trace["events"]:
        print(f"  {e['seq']:>4}  {e['ts'][:19]}  {e['actor']:<24} {e['event_type']}")
    if trace.get("decision"):
        d = trace["decision"]
        print(f"decision: {d['outcome']} {d['reason_code']} under {d['policy_set_version']}")
    return 0


def _explain_decision(
    decision: dict[str, Any], envelope: dict[str, Any], chain: list[dict[str, Any]], as_json: bool
) -> int:
    from atp_core import ActionEnvelope, Decision
    from atp_policy.explain import explain, format_explanation

    x = explain(Decision.model_validate(decision), ActionEnvelope.model_validate(envelope), chain)
    print(json.dumps(x.model_dump(mode="json"), indent=2) if as_json else format_explanation(x))
    return 0


def _cmd_policy_explain(args: argparse.Namespace) -> int:
    if args.suite:
        if not args.case:
            raise UsageError("--suite needs --case NAME")
        from atp_evals.regression.runner import decide_cases

        suite = _load_suite(args.suite)
        case = _case(suite, args.case)
        policy_file = args.policies or suite.policies or _policy_file(args)
        (result,) = decide_cases(suite, [case], policy_set=args.policy_set, policy_file=policy_file)
        if result.decision is None:
            raise UsageError(f"could not decide case: {result.error}")
        from atp_core import ActionEnvelope

        env = ActionEnvelope.model_validate(
            {
                "trace_id": result.trace_id,
                "principal": suite.delegations.principals[case.principal].model_dump(mode="json"),
                "agent": suite.delegations.principals[case.agent].model_dump(mode="json"),
                "delegation_grant_id": "suite",
                "capability": case.capability,
                "tool": case.tool,
                "action": case.action,
                "resource": case.resource,
                "arguments": dict(case.arguments),
            }
        )
        return _explain_decision(result.decision, env.model_dump(mode="json"), [], args.json)
    if not args.trace:
        raise UsageError("give a TRACE id, or --suite FILE --case NAME")
    runtime = _open_home(args.home)
    try:
        trace = _trace_dict(runtime, args.trace)
    finally:
        runtime.close()
    if not trace.get("decision") or not trace.get("envelope"):
        raise UsageError(f"trace {args.trace} has no recorded decision")
    return _explain_decision(
        trace["decision"], trace["envelope"], trace.get("delegation_chain") or [], args.json
    )


def _cmd_policy_diff(args: argparse.Namespace) -> int:
    from atp_policy import PolicySetNotFoundError
    from atp_policy.analysis import diff_policy_sets, format_diff

    reg = _registry(_policy_file(args))
    try:
        d = diff_policy_sets(reg.get(args.from_version), reg.get(args.to_version))
    except PolicySetNotFoundError as exc:
        raise UsageError(exc.message) from exc
    if args.json:
        print(json.dumps(d.model_dump(mode="json"), indent=2))
    else:
        print(format_diff(d))
        for k, v in d.details.items():
            print(f"    {k}: {json.dumps(v, default=str)}")
    return 0


def _cmd_policy_impact(args: argparse.Namespace) -> int:
    from atp_evals.analysis import format_impact, policy_impact

    policy_file = _policy_file(args)
    if args.suite:
        suite = _load_suite(args.suite)
        policy_file = args.policies or suite.policies or policy_file
    else:
        runtime = _open_home(args.home)
        try:
            suite = _suite_from_traces(runtime, args.limit)
        finally:
            runtime.close()
    try:
        report = policy_impact(
            suite,
            from_version=args.from_version,
            to_version=args.to_version,
            policy_file=policy_file,
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    print(
        json.dumps(report.model_dump(mode="json"), indent=2) if args.json else format_impact(report)
    )
    return 1 if (args.fail_on_widen and report.widened) else 0


def _cmd_policy_coverage(args: argparse.Namespace) -> int:
    from atp_policy import PolicySetNotFoundError
    from atp_policy.analysis import coverage_for, format_coverage

    policy_file = _policy_file(args)
    if args.suite:
        suite = _load_suite(args.suite)
        policy_file = args.policies or suite.policies or policy_file
    else:
        runtime = _open_home(args.home)
        try:
            suite = _suite_from_traces(runtime, args.limit)
        finally:
            runtime.close()
    reg = _registry(policy_file)
    version = args.policy_set or suite.policy_set
    try:
        policy_set = reg.get(version)
    except PolicySetNotFoundError as exc:
        raise UsageError(exc.message) from exc
    seen: dict[tuple[str, str], set[str]] = {}
    for c in suite.cases:
        seen.setdefault((c.tool, c.action), set()).update(c.arguments)
    rows = [coverage_for(policy_set, t, a, sorted(names)) for (t, a), names in sorted(seen.items())]
    if args.json:
        print(json.dumps([r.model_dump(mode="json") for r in rows], indent=2))
    else:
        print(format_coverage(rows, version))
    return 0


def _cmd_mutate(args: argparse.Namespace) -> int:
    from atp_evals.analysis import format_mutation, mutate
    from atp_evals.regression import TraceConversionError, case_from_trace

    policy_file = _policy_file(args)
    if args.suite:
        if not args.case:
            raise UsageError("--suite needs --case NAME")
        suite = _load_suite(args.suite)
        case = _case(suite, args.case)
        policy_file = args.policies or suite.policies or policy_file
    else:
        if not args.trace:
            raise UsageError("give a TRACE id, or --suite FILE --case NAME")
        from atp_evals.regression import merge_into_suite

        runtime = _open_home(args.home)
        try:
            trace = _trace_dict(runtime, args.trace)
        finally:
            runtime.close()
        try:
            delegations, case = case_from_trace(trace, name=f"trace-{args.trace}")
        except (TraceConversionError, ValueError) as exc:
            raise UsageError(f"trace could not be converted: {exc}") from exc
        suite = merge_into_suite(None, delegations, case)
        if case.source and case.source.policy_set:
            suite = suite.model_copy(update={"policy_set": case.source.policy_set})
    try:
        report = mutate(suite, case, policy_set=args.policy_set, policy_file=policy_file)
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    print(
        json.dumps(report.model_dump(mode="json"), indent=2)
        if args.json
        else format_mutation(report)
    )
    return 1 if report.unexpected else 0


def _cmd_evidence_export(args: argparse.Namespace) -> int:
    from atp_core import ATPError
    from atp_gateway.evidence import build_bundle

    runtime = _open_home(args.home)
    try:
        try:
            view = runtime.trust_plane.get_trace(args.trace)
        except ATPError as exc:
            raise UsageError(f"trace {args.trace}: {exc.message}") from exc
        bundle = build_bundle(view, include_excerpts=args.include_excerpts)
    finally:
        runtime.close()
    out = Path(args.out or f"atp-evidence-{args.trace}.json")
    out.write_text(json.dumps(bundle.model_dump(mode="json"), indent=2), encoding="utf-8")
    print(f"wrote {out}  bundle_hash={bundle.bundle_hash[:16]}...  events={len(bundle.events)}")
    if bundle.redactions:
        print("redacted: " + "; ".join(bundle.redactions))
    return 0


def _cmd_evidence_verify(args: argparse.Namespace) -> int:
    from atp_gateway.evidence import verify_bundle

    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read {args.file}: {exc}") from exc
    ok, detail = verify_bundle(data)
    print(("OK   " if ok else "FAIL ") + detail)
    return 0 if ok else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    import logging

    import uvicorn

    from atp_gateway import GatewaySettings, create_app
    from atp_gateway.settings import InsecureConfigurationError

    logging.basicConfig(level="INFO")
    try:
        app = create_app(GatewaySettings())
    except InsecureConfigurationError as exc:
        raise UsageError(f"refusing to start: {exc}") from exc
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_keygen(args: argparse.Namespace) -> int:
    from atp_gateway.__main__ import keygen

    keygen(["--write", args.write] if args.write else [])
    return 0


def _cmd_mcp_proxy(args: argparse.Namespace) -> int:
    from atp_adapter_mcp.proxy import main as proxy_main

    try:
        proxy_main(["--config", args.config, "--log-level", args.log_level])
    except (OSError, ValueError, RuntimeError) as exc:
        raise UsageError(f"mcp proxy: {str(exc)[:500]}") from exc
    return 0


def _cmd_mcp_init(args: argparse.Namespace) -> int:
    from atp_cli.mcp_cmds import init_config

    return init_config(
        out=Path(args.config),
        name=args.name,
        url=args.url,
        command=args.upstream_command,
        casefold=args.casefold,
        home_dir=args.home,
    )


def _cmd_mcp_wrap(args: argparse.Namespace) -> int:
    from atp_cli.mcp_cmds import wrap

    return wrap(
        config_path=Path(args.config),
        mode=args.mode,
        home_dir=args.home,
        name=args.name,
        url=args.url,
        command=args.upstream_command,
        log_level=args.log_level,
    )


# ---------------------------------------------------------------- parser
def _home_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--home", help="ATP home directory (default: $ATP_HOME or ./.atp)")


def _policies_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--policies", help="policy file (default: <home>/policies.yaml if present)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="atp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check prerequisites")
    d.add_argument("--port", type=int, default=8000)
    d.set_defaults(func=_cmd_doctor)

    demo = sub.add_parser("demo", help="run a documented demo")
    demo.add_argument("which", choices=["injection", "regression", "mcp", "wrap"])
    demo.add_argument("--out", help="where to write generated files")
    demo.set_defaults(func=_cmd_demo)

    # mcp
    mcp = sub.add_parser("mcp", help="protect an MCP server")
    msub = mcp.add_subparsers(dest="mcp_command", required=True)
    mi = msub.add_parser(
        "init", help="discover an MCP server's tools and write a reviewed-by-you proxy config"
    )
    mi.add_argument("--config", default="atp-mcp.yaml")
    mi.add_argument("--name", help="short server name (default: derived from the command)")
    mi.add_argument("--url", help="Streamable HTTP upstream instead of a command")
    mi.add_argument("--casefold", action=argparse.BooleanOptionalAction, default=None)
    _home_arg(mi)
    mi.add_argument("upstream_command", nargs="*", help="upstream command after `--`")
    mi.set_defaults(func=_cmd_mcp_init)
    mw = msub.add_parser(
        "wrap", help="serve a protected MCP server over stdio with the gateway in-process"
    )
    mw.add_argument("--config", default="atp-mcp.yaml")
    mw.add_argument("--mode", choices=["enforce", "shadow"], default="enforce")
    mw.add_argument("--name")
    mw.add_argument("--url")
    mw.add_argument("--log-level", default="warning")
    _home_arg(mw)
    mw.add_argument(
        "upstream_command", nargs="*", help="upstream command after `--` (first run only)"
    )
    mw.set_defaults(func=_cmd_mcp_wrap)
    mp = msub.add_parser(
        "proxy", help="serve the proxy against a remote gateway ($ATP_AGENT_TOKEN)"
    )
    mp.add_argument("--config", required=True)
    mp.add_argument("--log-level", default="info")
    mp.set_defaults(func=_cmd_mcp_proxy)
    legacy = sub.add_parser("mcp-proxy", help=argparse.SUPPRESS)
    legacy.add_argument("--config", required=True)
    legacy.add_argument("--log-level", default="info")
    legacy.set_defaults(func=_cmd_mcp_proxy)

    # traces
    tr = sub.add_parser("trace", help="inspect recorded decisions in the local store")
    tsub = tr.add_subparsers(dest="trace_command", required=True)
    tl = tsub.add_parser("list")
    tl.add_argument("--limit", type=int, default=20)
    tl.add_argument("--json", action="store_true")
    _home_arg(tl)
    tl.set_defaults(func=_cmd_trace_list)
    ts = tsub.add_parser("show")
    ts.add_argument("trace")
    ts.add_argument("--json", action="store_true")
    _home_arg(ts)
    ts.set_defaults(func=_cmd_trace_show)

    # regression
    rg = sub.add_parser("regression", help="turn recorded decisions into CI tests")
    rsub = rg.add_subparsers(dest="regression_command", required=True)
    ra = rsub.add_parser("add", help="pin a recorded decision from the local store as a case")
    ra.add_argument("trace")
    ra.add_argument("--suite", default="atp-regression.yaml")
    ra.add_argument("--name")
    _home_arg(ra)
    ra.set_defaults(func=_cmd_regression_add)

    t = sub.add_parser("test", help="run a security regression suite (exit 1 on any change)")
    t.add_argument("suite")
    t.add_argument("--policy-set", help="override the suite's policy set")
    _policies_arg(t)
    _home_arg(t)
    t.add_argument("--json", help="write a JSON report")
    t.add_argument("--junit", help="write a JUnit XML report")
    t.add_argument("--quiet", action="store_true")
    t.set_defaults(func=_cmd_test)

    r = sub.add_parser("record", help="pin a trace from a remote gateway (operator key)")
    r.add_argument("--trace", required=True)
    r.add_argument("--gateway", default="http://127.0.0.1:8000")
    r.add_argument("--suite", default="atp-regression.yaml")
    r.add_argument("--name")
    r.add_argument("--operator-key")
    r.set_defaults(func=_cmd_record)

    # policy
    po = sub.add_parser("policy", help="explain, diff, impact and coverage")
    psub = po.add_subparsers(dest="policy_command", required=True)
    pe = psub.add_parser("explain", help="why a decision happened and what would need to change")
    pe.add_argument("trace", nargs="?")
    pe.add_argument("--suite")
    pe.add_argument("--case")
    pe.add_argument("--policy-set")
    _policies_arg(pe)
    _home_arg(pe)
    pe.add_argument("--json", action="store_true")
    pe.set_defaults(func=_cmd_policy_explain)
    pd = psub.add_parser("diff", help="structural diff of two policy sets")
    pd.add_argument("from_version")
    pd.add_argument("to_version")
    _policies_arg(pd)
    _home_arg(pd)
    pd.add_argument("--json", action="store_true")
    pd.set_defaults(func=_cmd_policy_diff)
    pi = psub.add_parser("impact", help="what a policy change does to recorded actions")
    pi.add_argument("--from", dest="from_version", required=True)
    pi.add_argument("--to", dest="to_version", required=True)
    pi.add_argument("--suite", help="use a suite's cases instead of the local store")
    pi.add_argument("--limit", type=int, default=200, help="traces to read from the store")
    pi.add_argument("--fail-on-widen", action="store_true", help="exit 1 if any DENY -> ALLOW")
    _policies_arg(pi)
    _home_arg(pi)
    pi.add_argument("--json", action="store_true")
    pi.set_defaults(func=_cmd_policy_impact)
    pc = psub.add_parser("coverage", help="which dimensions of each recorded action are guarded")
    pc.add_argument("--suite")
    pc.add_argument("--policy-set")
    pc.add_argument("--limit", type=int, default=200)
    _policies_arg(pc)
    _home_arg(pc)
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=_cmd_policy_coverage)

    mu = sub.add_parser("mutate", help="probe the policy around a recorded action (authorize only)")
    mu.add_argument("trace", nargs="?")
    mu.add_argument("--suite")
    mu.add_argument("--case")
    mu.add_argument("--policy-set")
    _policies_arg(mu)
    _home_arg(mu)
    mu.add_argument("--json", action="store_true")
    mu.set_defaults(func=_cmd_mutate)

    ev = sub.add_parser("evidence", help="export / verify portable evidence bundles")
    esub = ev.add_subparsers(dest="evidence_command", required=True)
    ee = esub.add_parser("export")
    ee.add_argument("trace")
    ee.add_argument("--out")
    ee.add_argument("--include-excerpts", action="store_true")
    _home_arg(ee)
    ee.set_defaults(func=_cmd_evidence_export)
    evf = esub.add_parser("verify")
    evf.add_argument("file")
    evf.set_defaults(func=_cmd_evidence_verify)

    s = sub.add_parser("serve", help="run a persistent HTTP gateway (needs .env keys)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=_cmd_serve)

    k = sub.add_parser("keygen", help="generate gateway keys for `atp serve`")
    k.add_argument("--write", metavar="PATH")
    k.set_defaults(func=_cmd_keygen)
    return p


def main(argv: list[str] | None = None) -> None:
    raw = list(sys.argv[1:] if argv is None else argv)
    head, command = _split_command(raw)
    args = build_parser().parse_args(head)
    if command:
        if getattr(args, "mcp_command", None) not in ("init", "wrap"):
            _err("a `--` command is only accepted by `atp mcp init` and `atp mcp wrap`")
            sys.exit(2)
        args.upstream_command = command
    try:
        code: int = args.func(args)
    except UsageError as exc:
        _err(f"error: {exc}")
        code = 2
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
