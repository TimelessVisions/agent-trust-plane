"""``atp`` — the Agent Trust Plane command line.

atp doctor                      check prerequisites
atp demo injection|regression|mcp
atp test SUITE.yaml [--policy-set V] [--json out.json] [--junit out.xml]
atp record --trace ID [--gateway URL] [--suite file.yaml] [--name NAME]
atp serve [--port 8000]         run a persistent gateway (needs .env keys)
atp keygen [--write .env]
atp mcp-proxy --config atp-mcp.yaml
atp mcp-init [--out atp-mcp.yaml]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


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
    return demos.demo_mcp(Path(args.out) if args.out else None)


def _cmd_test(args: argparse.Namespace) -> int:
    from atp_evals.regression import format_text, load_suite, run_suite, to_json, to_junit

    try:
        suite = load_suite(args.suite)
    except (OSError, ValueError) as exc:
        print(f"invalid suite {args.suite}: {exc}", file=sys.stderr)
        return 2
    report = run_suite(suite, policy_set=args.policy_set)
    if args.json:
        Path(args.json).write_text(json.dumps(to_json(report), indent=2), encoding="utf-8")
    if args.junit:
        Path(args.junit).write_text(to_junit(report), encoding="utf-8")
    if not args.quiet:
        print(format_text(report))
    return 0 if report.ok else 1


def _cmd_record(args: argparse.Namespace) -> int:
    from atp_adapter_http import GatewayError, TrustPlaneClient
    from atp_evals.regression import (
        TraceConversionError,
        case_from_trace,
        dump_suite,
        load_suite,
        merge_into_suite,
    )

    key = args.operator_key or os.environ.get("ATP_OPERATOR_KEY")
    if not key:
        print(
            "record needs the operator key (--operator-key or $ATP_OPERATOR_KEY)", file=sys.stderr
        )
        return 2
    client = TrustPlaneClient(args.gateway, operator_key=key)
    try:
        trace = client.get_trace(args.trace)
    except GatewayError as exc:
        print(f"could not fetch trace: {exc}", file=sys.stderr)
        return 2
    suite_path = Path(args.suite)
    existing = load_suite(suite_path) if suite_path.exists() else None
    try:
        delegations, case = case_from_trace(trace, name=args.name, gateway=args.gateway)
        suite = merge_into_suite(existing, delegations, case)
    except (TraceConversionError, ValueError) as exc:
        print(f"trace {args.trace} could not be converted: {exc}", file=sys.stderr)
        return 2
    dump_suite(suite, suite_path)
    print(
        f"recorded '{case.name}': expect {case.expect.outcome.value}"
        + (f" {case.expect.reason_code}" if case.expect.reason_code else "")
        + f" -> {suite_path} ({len(suite.cases)} case(s))"
    )
    print("the expectation is the decision the gateway made; review it before committing")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import logging

    import uvicorn

    from atp_gateway import GatewaySettings, create_app
    from atp_gateway.settings import InsecureConfigurationError

    logging.basicConfig(level="INFO")
    try:
        app = create_app(GatewaySettings())
    except InsecureConfigurationError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_keygen(args: argparse.Namespace) -> int:
    from atp_gateway.__main__ import keygen

    keygen(["--write", args.write] if args.write else [])
    return 0


def _cmd_mcp_proxy(args: argparse.Namespace) -> int:
    from atp_adapter_mcp.proxy import main as proxy_main

    proxy_main(["--config", args.config, "--log-level", args.log_level])
    return 0


def _cmd_mcp_init(args: argparse.Namespace) -> int:
    template = """\
# Agent Trust Plane MCP proxy config. Run: atp mcp-proxy --config atp-mcp.yaml
# The agent credential is read from $ATP_AGENT_TOKEN (issue one with the operator key:
#   POST /agents/<id>/credentials). Tools not listed below are denied by default.
gateway: http://127.0.0.1:8000
server_name: notes
principal: { id: alice, kind: human }
agent: { id: notes-assistant, kind: agent }
delegation_grant_id: REPLACE_WITH_GRANT_ID
agent_token_env: ATP_AGENT_TOKEN
upstream:
  command: python
  args: [-m, notes_mcp_server]
  env: { NOTES_DIR: ./notes }
tools:
  - mcp_tool: write_note
    tool: mcp.notes
    action: write_note
    capability: notes:write
    resource_template: "note:{id}"
    resource_arguments: [id]
  - mcp_tool: read_note
    tool: mcp.notes
    action: read_note
    capability: notes:read
    resource_template: "note:{id}"
    resource_arguments: [id]
"""
    out = Path(args.out)
    if out.exists():
        print(f"{out} exists; not overwriting", file=sys.stderr)
        return 2
    out.write_text(template, encoding="utf-8")
    print(f"wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="atp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="check prerequisites")
    d.add_argument("--port", type=int, default=8000)
    d.set_defaults(func=_cmd_doctor)

    demo = sub.add_parser("demo", help="run a documented demo")
    demo.add_argument("which", choices=["injection", "regression", "mcp"])
    demo.add_argument("--out", help="where to write generated files (regression suite / mcp dir)")
    demo.set_defaults(func=_cmd_demo)

    t = sub.add_parser("test", help="run a security regression suite")
    t.add_argument("suite")
    t.add_argument("--policy-set", help="override the suite's policy set")
    t.add_argument("--json", help="write a JSON report")
    t.add_argument("--junit", help="write a JUnit XML report")
    t.add_argument("--quiet", action="store_true")
    t.set_defaults(func=_cmd_test)

    r = sub.add_parser("record", help="turn a recorded trace into a regression case")
    r.add_argument("--trace", required=True)
    r.add_argument("--gateway", default="http://127.0.0.1:8000")
    r.add_argument("--suite", default="atp-regression.yaml")
    r.add_argument("--name")
    r.add_argument("--operator-key")
    r.set_defaults(func=_cmd_record)

    s = sub.add_parser("serve", help="run a persistent gateway")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=_cmd_serve)

    k = sub.add_parser("keygen", help="generate gateway keys")
    k.add_argument("--write", metavar="PATH")
    k.set_defaults(func=_cmd_keygen)

    m = sub.add_parser("mcp-proxy", help="run the MCP stdio proxy")
    m.add_argument("--config", required=True)
    m.add_argument("--log-level", default="info")
    m.set_defaults(func=_cmd_mcp_proxy)

    i = sub.add_parser("mcp-init", help="write a starter proxy config")
    i.add_argument("--out", default="atp-mcp.yaml")
    i.set_defaults(func=_cmd_mcp_init)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
