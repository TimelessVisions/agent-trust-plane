"""A stand-in for ``claude -p`` / ``codex exec`` used by the live-runner tests.

It never talks to a model. Depending on its flags it records that it ran, optionally connects
to the MCP server named in ``--mcp-config`` and behaves like a fully obedient agent (the user
task's ground truth, then the ground truth of whatever injection task the server was started
with), and exits the way a real CLI would, including the usage-limit exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio


def _result(
    text: str,
    *,
    is_error: bool = False,
    tools: list[str] | None = None,
    model: str = "fake-model-1",
    init_override: dict | None = None,
    result_extra: dict | None = None,
    rate_limit_status: str = "allowed",
    tool_events: list[dict] | None = None,
) -> None:
    init = {
        "type": "system",
        "subtype": "init",
        "tools": ["mcp__dojo__x"] if tools is None else tools,
        "mcp_servers": [{"name": "dojo", "status": "connected"}],
        "plugins": [],
        "model": model,
        "apiKeySource": "none",
        "claude_code_version": "0.0.0-fake",
        **(init_override or {}),
    }
    print(json.dumps(init))
    for call in tool_events or []:  # what a real stream shows: the call, then what came back
        use = {"type": "tool_use", "id": call["id"], "name": call["name"], "input": call["input"]}
        print(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [use]}}))
        res = {"type": "tool_result", "tool_use_id": call["id"], "is_error": call["is_error"],
               "content": [{"type": "text", "text": call["text"]}]}
        print(json.dumps({"type": "user", "message": {"role": "user", "content": [res]}}))
    # Real Claude Code emits this on healthy runs too: it must never read as a usage limit.
    limit = {"type": "rate_limit_event", "rate_limit_info": {"status": rate_limit_status}}
    print(json.dumps(limit))
    print(json.dumps({"type": "result", "is_error": is_error, "result": text, **(result_extra or {})}))


async def _obey(
    config: Path, suite_name: str, user_task: str, only: list[str]
) -> list[dict]:
    from atp_bench.dojo import load_suite
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["dojo"]
    params = StdioServerParameters(
        command=server["command"], args=server["args"], env=server.get("env")
    )
    args = server["args"]
    if "--injection-task" not in args:  # behind `atp mcp wrap`: the upstream is in its config
        import yaml

        config_file = Path(args[args.index("--config") + 1])
        args = yaml.safe_load(config_file.read_text(encoding="utf-8"))["upstream"]["args"]
    injection = args[args.index("--injection-task") + 1]
    suite = load_suite(suite_name)
    calls = suite.user_ground_truth(user_task, suite.default_env())
    if injection != "none":
        calls += suite.injection_ground_truth(injection, suite.env_with_injection(injection))
    if only:  # a lazy agent: connects and makes only these (argument-less) calls
        calls = [type(calls[0])(function=name, args={}) for name in only]
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        seen: list[dict] = []
        for n, call in enumerate(calls):
            reply = await session.call_tool(call.function, call.args)
            text = " ".join(c.text for c in reply.content if getattr(c, "type", "") == "text")
            seen.append({"id": f"t{n}", "name": f"mcp__dojo__{call.function}",
                         "input": call.args, "is_error": bool(reply.is_error), "text": text})
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt")
    parser.add_argument("--mcp-config", type=Path)
    parser.add_argument("--counter", type=Path, help="append one line per invocation")
    parser.add_argument("--obey", metavar="SUITE:USER_TASK")
    parser.add_argument("--only", nargs="*", default=[], help="make only these no-arg calls")
    parser.add_argument("--emit", type=Path, help="print this file instead of a result")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--spawn-child", type=Path, help="start a long-lived child")
    parser.add_argument("--limit", action="store_true", help="exit like a usage-limited CLI")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--stderr", default="")
    parser.add_argument("--init-tools", nargs="*", default=None, help="tools the init event lists")
    parser.add_argument("--model", "-m", default="fake-model-1")
    parser.add_argument("--init-override", default=None, help="JSON merged into the init event")
    parser.add_argument("--result-extra", default=None, help="JSON merged into the result event")
    parser.add_argument("--rate-limit-status", default="allowed")
    parser.add_argument("--drift-after", type=int, default=None,
                        help="after this many invocations (needs --counter) report another model")
    args, _unknown = parser.parse_known_args()
    if args.counter:
        with args.counter.open("a", encoding="utf-8") as fh:
            fh.write(f"{args.prompt!r}\n")
    if args.stderr:
        print(args.stderr, file=sys.stderr)
    if args.spawn_child:
        import subprocess

        child = subprocess.Popen(  # detached from our pipes: a clean exit must not wait for it
            [sys.executable, "-c", "import time; time.sleep(600)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        args.spawn_child.write_text(str(child.pid), encoding="utf-8")
    if args.emit:
        sys.stdout.write(args.emit.read_text(encoding="utf-8"))
        return args.exit_code
    if args.limit:
        _result("Claude AI usage limit reached|1760000000", is_error=True)
        print("usage limit reached", file=sys.stderr)
        return 1
    if args.sleep:
        import time

        time.sleep(args.sleep)
    tool_events: list[dict] = []
    if args.obey:
        suite_name, user_task = args.obey.split(":")
        tool_events = anyio.run(_obey, args.mcp_config, suite_name, user_task, args.only)
    drifted_model = None
    if args.drift_after is not None and args.counter:
        if len(args.counter.read_text(encoding="utf-8").splitlines()) > args.drift_after:
            drifted_model = "drifted-model"
    _result(
        "Done.",
        tools=args.init_tools,
        model=drifted_model if drifted_model else args.model,
        init_override=json.loads(args.init_override) if args.init_override else None,
        result_extra=json.loads(args.result_extra) if args.result_extra else None,
        rate_limit_status=args.rate_limit_status,
        tool_events=tool_events,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
