"""Run a code sample against test cases in a separate Python process.

This is isolation for correctness checking of known sample code, NOT a security
sandbox: never run untrusted code with it outside a disposable machine or container.
Each run gets: an isolated interpreter (-I), an empty temporary working directory,
a minimal environment, a wall-clock timeout and, on POSIX, CPU and memory limits.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 5.0
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024

_HARNESS = r"""
import json, sys, traceback

def norm(value):
    # Compare through JSON so tuples equal lists and keys are strings, as in the test file.
    return json.loads(json.dumps(value))

spec = json.loads(sys.stdin.read())
results = []
namespace = {"__name__": "candidate"}
try:
    exec(compile(spec["code"], "<candidate>", "exec"), namespace)
    fn = namespace[spec["function"]]
except Exception as exc:
    print(json.dumps({"load_error": f"{type(exc).__name__}: {exc}"}))
    sys.exit(0)
for case in spec["cases"]:
    entry = {"args": case["args"]}
    try:
        got = norm(fn(*case["args"]))
        entry["got"] = got
        if "raises" in case:
            entry["passed"] = False
            entry["detail"] = f"expected {case['raises']}, got return value {got!r}"
        else:
            entry["passed"] = got == case["expected"]
            if not entry["passed"]:
                entry["detail"] = f"expected {case['expected']!r}, got {got!r}"
    except Exception as exc:
        name = type(exc).__name__
        entry["raised"] = name
        entry["passed"] = case.get("raises") == name
        if not entry["passed"]:
            want = case.get("raises") or "a return value"
            entry["detail"] = f"expected {want}, raised {name}: {exc}"
    results.append(entry)
print(json.dumps({"results": results}))
"""


@dataclass(frozen=True)
class CaseResult:
    args: list[Any]
    passed: bool
    got: Any = None
    raised: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class RunResult:
    cases: tuple[CaseResult, ...]
    error: str | None = None  # load error, timeout or crash: no case result is trustworthy

    @property
    def ok(self) -> bool:
        return self.error is None and all(c.passed for c in self.cases)

    @property
    def failed(self) -> tuple[CaseResult, ...]:
        return tuple(c for c in self.cases if not c.passed)


def _limits() -> None:  # pragma: no cover - runs in the child process
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (int(DEFAULT_TIMEOUT) + 1, int(DEFAULT_TIMEOUT) + 1))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))


def run_cases(code: str, function: str, cases: list[dict[str, Any]], timeout: float = DEFAULT_TIMEOUT) -> RunResult:
    spec = json.dumps({"code": code, "function": function, "cases": cases})
    with tempfile.TemporaryDirectory(prefix="annoqa-run-") as tmp:
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"}
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", _HARNESS],
                input=spec,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=Path(tmp),
                env=env,
                preexec_fn=_limits if os.name == "posix" else None,  # noqa: PLW1509
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RunResult((), error=f"timed out after {timeout:g}s")
    if proc.returncode != 0:
        tail = (proc.stderr.strip().splitlines() or ["no output"])[-1]
        return RunResult((), error=f"process exited with {proc.returncode}: {tail}")
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return RunResult((), error="harness produced no result (the code may print to stdout or exit early)")
    if "load_error" in payload:
        return RunResult((), error=f"could not load the function: {payload['load_error']}")
    return RunResult(
        tuple(
            CaseResult(
                args=r["args"],
                passed=bool(r["passed"]),
                got=r.get("got"),
                raised=r.get("raised"),
                detail=r.get("detail", ""),
            )
            for r in payload["results"]
        )
    )


def outputs_differ(candidate: str, reference: str, function: str, args: list[Any]) -> tuple[bool, str]:
    """Run both implementations on one input. True if their behaviour differs (a confirmed bug)."""
    probe = [{"args": args, "expected": None}]
    cand = run_cases(candidate, function, probe)
    ref = run_cases(reference, function, probe)
    if ref.error or not ref.cases:
        return False, f"reference could not run on this input: {ref.error}"
    if cand.error or not cand.cases:
        return True, f"candidate failed to run: {cand.error}"
    c, r = cand.cases[0], ref.cases[0]
    if (c.raised, c.got) == (r.raised, r.got):
        return False, f"both give {_describe(c)}"
    return True, f"candidate gives {_describe(c)}, reference gives {_describe(r)}"


def _describe(c: CaseResult) -> str:
    return f"raises {c.raised}" if c.raised else repr(c.got)
