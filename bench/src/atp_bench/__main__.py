"""CLI.

python -m atp_bench run --layer atp --layer open --suite banking --out results/ [--slice N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from atp_bench.annotations import DEFAULT_ROOT
from atp_bench.dojo import SUITES
from atp_bench.layers.agentgateway_layer import AgentgatewayLayer
from atp_bench.layers.atp_layer import AtpLayer
from atp_bench.layers.docker_layer import DockerMcpLayer
from atp_bench.layers.name_only_layer import NameOnlyLayer
from atp_bench.layers.open_layer import OpenLayer
from atp_bench.layers.toolhive_layer import ToolhiveLayer
from atp_bench.live import AGENTS, plan_live, run_live
from atp_bench.live.runner import DEFAULT_AGENT_TIMEOUT_S, LIVE_LAYERS
from atp_bench.run import run_benchmark

LAYERS = {
    "agentgateway": AgentgatewayLayer,
    "atp": AtpLayer,
    "docker-mcp-gateway": DockerMcpLayer,
    "name-only": NameOnlyLayer,
    "open": OpenLayer,
    "toolhive": ToolhiveLayer,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m atp_bench")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="replay ground truths through each layer and score them")
    run.add_argument("--layer", action="append", choices=sorted(LAYERS), required=True)
    run.add_argument("--suite", action="append", choices=SUITES, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--slice", type=int, default=None, dest="slice_n",
                     help="first N user tasks per suite, in numeric order")  # fmt: skip
    run.add_argument("--injections-per-task", type=int, default=None,
                     help="first K injection tasks (numeric order); 0 = utility only")  # fmt: skip
    run.add_argument("--annotations", type=Path, default=DEFAULT_ROOT)
    run.add_argument("--no-require-preregistration", action="store_true",
                     help="skip the pre-registration check (development runs only)")  # fmt: skip
    live = sub.add_parser(
        "live",
        help="plan (default) or run (--execute) real agents on the owner's subscriptions",
    )
    live.add_argument("--agent", action="append", choices=sorted(AGENTS), required=True)
    live.add_argument("--layer", action="append", choices=LIVE_LAYERS, required=True)
    live.add_argument("--suite", action="append", choices=SUITES, required=True)
    live.add_argument("--out", type=Path, required=True)
    live.add_argument("--slice", type=int, default=None, dest="slice_n",
                      help="first N annotated user tasks per suite")  # fmt: skip
    live.add_argument("--user-task", action="append", default=None, dest="user_tasks")
    live.add_argument("--clean-only", action="store_true",
                      help="plan only the clean run of each task: no injection, no "
                           "pre-registration needed (smoke tests)")  # fmt: skip
    live.add_argument("--model", default=None,
                      help="model passed to the agent and recorded; never chosen for you")  # fmt: skip
    live.add_argument("--no-resume", action="store_true", help="run again even where cached")
    live.add_argument("--timeout", type=float, default=DEFAULT_AGENT_TIMEOUT_S,
                      help="seconds before one agent run is killed")  # fmt: skip
    live.add_argument("--execute", action="store_true",
                      help="actually start the agents (spends subscription quota)")  # fmt: skip
    live.add_argument("--accept-codex-shell-risk", action="store_true",
                      help="allow Codex runs although its shell cannot be removed")  # fmt: skip
    live.add_argument("--no-require-preregistration", action="store_true",
                      help="skip the pre-registration check (development runs only)")  # fmt: skip
    args = parser.parse_args(argv)

    if args.command == "live":
        plan = plan_live(
            [AGENTS[name] for name in args.agent], args.layer, args.suite,
            user_tasks=args.user_tasks, slice_n=args.slice_n, clean_only=args.clean_only,
        )  # fmt: skip
        if not args.execute:
            print("dry run: nothing started. Add --execute to run; this uses subscription quota.")
            return 0
        live_summary = run_live(
            plan, args.out, resume=not args.no_resume, agent_timeout_s=args.timeout,
            require_preregistration=not args.no_require_preregistration,
            allow_codex_shell=args.accept_codex_shell_risk, model=args.model,
        )  # fmt: skip
        print(live_summary.to_markdown())
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "summary.md").write_text(live_summary.to_markdown(), encoding="utf-8")
        return 3 if live_summary.stopped else 0

    summary = run_benchmark(
        [LAYERS[name]() for name in args.layer],
        args.suite,
        args.out,
        injections_per_task=args.injections_per_task,
        require_preregistration=not args.no_require_preregistration,
        slice_n=args.slice_n,
        annotations_root=args.annotations,
    )
    print(summary.to_markdown())
    return 0


if __name__ == "__main__":
    sys.exit(main())
