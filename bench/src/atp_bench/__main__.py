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
from atp_bench.layers.open_layer import OpenLayer
from atp_bench.layers.toolhive_layer import ToolhiveLayer
from atp_bench.run import run_benchmark

LAYERS = {
    "agentgateway": AgentgatewayLayer,
    "atp": AtpLayer,
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
    args = parser.parse_args(argv)

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
