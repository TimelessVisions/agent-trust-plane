"""Generate the 1.0 compatibility golden files in ``tests/compat/1.0/``.

    uv run --no-sync python scripts/gen_compat.py [OUT_DIR]

The output is deterministic: the clock, ids, tokens and keys are fixed for
the duration of the run (see ``deterministic``) and the script re-executes
itself with ``PYTHONHASHSEED=0``, so running it twice gives byte-identical
files. ``tests/compat/test_compat.py`` loads the checked-in
files with the current code, and also calls ``generate`` into a temporary
directory to compare today's ``--json`` shapes with the frozen ones.

The scenario is the ``atp mcp wrap`` loop, in-process: a home in a temporary
directory, the notes MCP server's tools proposed into ``atp-mcp.yaml``, one
allowed ``write_note`` (authorized over HTTP, executed, outcome reported)
and one denied ``delete_note``, both pinned into a regression suite.

Regenerate only on purpose (Task H1 does, once, at the freeze). After the
freeze a change here that changes a frozen shape is a breaking change.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import random
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "tests" / "compat" / "1.0"
FIXED_NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
SERVER = "notes"
UPSTREAM_COMMAND = ["python", "-m", "notes_mcp_server"]

POLICIES_YAML = """\
# Declared policy sets for the 1.0 compat golden files (see docs/policies/policies.md).
version: 1
policy_sets:
  - version: notes-v1
    description: notes via atp mcp wrap
    rules:
      - id: short-notes
        applies_to: {tool: mcp.notes, action: write_note}
        kind: argument_max_length
        argument: text
        max_length: 2000
  - version: notes-v2
    description: notes, tighter
    rules:
      - id: tiny-notes
        applies_to: {tool: mcp.notes, action: write_note}
        kind: argument_max_length
        argument: text
        max_length: 4
      - id: id-required
        applies_to: {tool: mcp.notes, action: write_note}
        kind: argument_required
        arguments: [id]
      - id: never-delete
        applies_to: {tool: mcp.notes, action: delete_note}
        kind: deny
      - id: review-lists
        applies_to: {tool: mcp.notes, action: list_notes}
        kind: require_approval
        approver_role: approver
  - version: all-kinds-v1
    description: every rule kind and field, for the frozen file format
    include: [payments]
    approval_threshold: 250
    rules:
      - id: pay-max
        description: no single payment over 1000
        applies_to: {tool: payments, action: send}
        kind: argument_max
        argument: amount
        max: 1000
      - id: pay-min
        applies_to: {tool: payments, action: send}
        kind: argument_min
        argument: amount
        min: 1
      - id: pay-currency
        applies_to: {tool: payments, action: send}
        kind: argument_allowed_values
        argument: currency
        values: [USD, EUR]
      - id: note-tags
        applies_to: {tool: mcp.notes, action: write_note}
        kind: argument_subset_of
        argument: tags
        values: [work, home, 7, true]
        optional: true
      - id: memo-length
        applies_to: {tool: payments, action: send}
        kind: argument_max_length
        argument: memo
        max_length: 140
        optional: true
      - id: pay-required
        applies_to: {tool: payments, action: send}
        kind: argument_required
        arguments: [amount, currency, destination]
      - id: no-raw-sql
        applies_to: {tool: '*'}
        kind: argument_forbidden
        arguments: [raw_sql]
      - id: no-refunds
        applies_to: {tool: payments, action: refund}
        kind: deny
      - id: review-payouts
        applies_to: {tool: payments, action: payout}
        kind: require_approval
        approver_role: finance
"""


# ------------------------------------------------------------ determinism
class _Clock:
    """Fixed start, one millisecond per reading: ordered and reproducible."""

    def __init__(self, start: datetime = FIXED_NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now = self.now + timedelta(milliseconds=1)
        return self.now


def _clock_code() -> datetime:
    # Runs with atp_core.timeutil's globals once its code is swapped in.
    return _compat_clock()  # type: ignore[name-defined,no-any-return]  # noqa: F821


@contextlib.contextmanager
def deterministic() -> Iterator[_Clock]:
    """Fix every source of variation the scenario touches, then restore them:
    ``uuid.uuid4``, the OS randomness behind ``secrets`` and ``os.urandom``,
    Ed25519 key generation, and ``atp_core.utcnow``."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import atp_core.timeutil as timeutil

    rng = random.Random(1_000)
    clock = _Clock()
    saved: list[tuple[Any, str, Any]] = []

    def patch(obj: Any, name: str, value: Any) -> None:
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def fake_bytes(n: int) -> bytes:
        return rng.randbytes(n)

    def fake_generate(cls: type[Ed25519PrivateKey]) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(rng.randbytes(32))

    patch(uuid, "uuid4", lambda: uuid.UUID(int=rng.getrandbits(128), version=4))
    patch(random, "_urandom", fake_bytes)
    patch(os, "urandom", fake_bytes)
    patch(Ed25519PrivateKey, "generate", classmethod(fake_generate))
    ticks = iter(range(1, 1 << 62))
    patch(time, "perf_counter", lambda: next(ticks) / 1000)  # 1 ms per reading
    # utcnow is bound by reference in defaults and pydantic default factories,
    # so swap its code rather than the name: every reference sees the clock.
    timeutil._compat_clock = clock  # type: ignore[attr-defined]
    patch(timeutil.utcnow, "__code__", _clock_code.__code__)
    try:
        yield clock
    finally:
        for obj, name, value in reversed(saved):
            setattr(obj, name, value)
        del timeutil._compat_clock  # type: ignore[attr-defined]


# ------------------------------------------------------------ helpers
def _run_cli(*argv: str) -> tuple[int, str]:
    from atp_cli.main import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        try:
            main(list(argv))
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return code, buf.getvalue()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _import_everything() -> None:
    """Import the modules that read the clock before patching, so their
    ``utcnow`` references exist to be replaced."""
    import atp_adapter_http  # noqa: F401
    import atp_adapter_mcp  # noqa: F401
    import atp_cli.home
    import atp_cli.main
    import atp_cli.mcp_cmds  # noqa: F401
    import atp_evals.analysis
    import atp_evals.regression  # noqa: F401
    import atp_gateway
    import atp_gateway.evidence
    import atp_gateway.local  # noqa: F401
    import atp_identity  # noqa: F401
    import atp_policy
    import atp_policy.explain  # noqa: F401

    for name in list(sys.modules):
        if name.startswith("atp_"):
            __import__(name)


def _discover_tools() -> list[Any]:
    from atp_adapter_mcp import UpstreamConfig
    from atp_cli.mcp_cmds import _discover

    return _discover(UpstreamConfig(command=sys.executable, args=("-m", "notes_mcp_server")))


# ------------------------------------------------------------ the scenario
def generate(out: Path) -> dict[str, Path]:
    """Write every golden file into ``out``. Returns name -> path."""
    from fastapi.testclient import TestClient

    from atp_adapter_mcp import UpstreamConfig, dump_config, load_config, propose_config
    from atp_adapter_mcp.discovery import render_header
    from atp_cli.home import AtpHome
    from atp_cli.mcp_cmds import seed_session
    from atp_core import ActionEnvelope, Provenance, ReasonCode, new_trace_id
    from atp_gateway import build_runtime, create_app
    from atp_gateway.evidence import build_bundle

    _import_everything()
    tools = _discover_tools()  # a subprocess: outside the patched region
    out.mkdir(parents=True, exist_ok=True)
    # Use the destination's filesystem: Windows cannot compute relative paths
    # across different drives when regression-add records the suite path.
    work = Path(tempfile.mkdtemp(prefix="atp-compat-", dir=out.parent))
    files: dict[str, Path] = {}
    try:
        with deterministic():
            home = AtpHome(work / ".atp")
            # atp-mcp.yaml, exactly as `atp mcp init` writes it
            upstream = UpstreamConfig(command=UPSTREAM_COMMAND[0], args=tuple(UPSTREAM_COMMAND[1:]))
            proposal = propose_config(SERVER, upstream, tools, scope_dirs=[])
            config = proposal.config.model_copy(update={"policy_set": "notes-v1"})
            files["atp-mcp.yaml"] = out / "atp-mcp.yaml"
            dump_config(
                config,
                files["atp-mcp.yaml"],
                header=render_header(proposal, " ".join(UPSTREAM_COMMAND)),
            )
            config = load_config(files["atp-mcp.yaml"])
            files["policies.yaml"] = out / "policies.yaml"
            files["policies.yaml"].write_text(POLICIES_YAML, encoding="utf-8")

            home.ensure(human=config.principal.id)
            shutil.copyfile(files["policies.yaml"], home.policy_path)
            settings = home.settings(
                default_policy_set=config.policy_set, external_tools=config.mapped_tools
            )
            runtime = build_runtime(settings)
            try:
                app = create_app(settings, runtime=runtime)
                from atp_adapter_http import TrustPlaneClient

                operator = TrustPlaneClient.for_app(app, operator_key=runtime.operator_key)
                token, grant_id = seed_session(operator, config)

                def envelope(action: str, arguments: dict[str, Any]) -> dict[str, Any]:
                    mapping = config.mapping_for(action)
                    assert mapping is not None, action
                    env = ActionEnvelope(
                        trace_id=new_trace_id(),
                        principal=config.principal,
                        agent=config.agent_ref,
                        delegation_grant_id=grant_id,
                        capability=mapping.capability,
                        tool=mapping.envelope_tool,
                        action=mapping.action,
                        resource=mapping.resource_for(arguments),
                        arguments=arguments,
                        provenance=Provenance(task_description="mcp tools/call via atp-proxy"),
                    )
                    body: dict[str, Any] = env.model_dump(mode="json")
                    return body

                auth = {"Authorization": f"Bearer {token}"}
                op = {"X-ATP-Operator-Key": runtime.operator_key}
                with TestClient(app) as http:
                    allow_req = envelope("write_note", {"id": "todo", "text": "buy milk"})
                    r = http.post("/authorize", json=allow_req, headers=auth)
                    assert r.status_code == 200, r.text
                    allow_resp = r.json()
                    assert allow_resp["decision"]["outcome"] == "ALLOW", allow_resp
                    grant = allow_resp["execution_grant"]
                    r = http.post(
                        "/execute",
                        json={"envelope": allow_req, "execution_grant": grant["token"]},
                        headers=auth,
                    )
                    assert r.status_code == 200, r.text
                    r = http.post(
                        f"/executions/{grant['grant_id']}/outcome",
                        json={"succeeded": True, "summary": {"is_error": False}},
                        headers=auth,
                    )
                    assert r.status_code == 200, r.text

                    deny_req = envelope("delete_note", {"id": "todo"})
                    r = http.post("/authorize", json=deny_req, headers=auth)
                    assert r.status_code == 200, r.text
                    assert r.json()["decision"]["outcome"] == "DENY", r.text

                    trace_id = allow_req["trace_id"]
                    r = http.get(f"/traces/{trace_id}", headers=op)
                    assert r.status_code == 200, r.text
                    trace_export = r.json()
                bundle = build_bundle(runtime.trust_plane.get_trace(trace_id))
            finally:
                runtime.close()

            files["http/authorize-request.json"] = out / "http" / "authorize-request.json"
            _write_json(files["http/authorize-request.json"], allow_req)
            files["http/authorize-response.json"] = out / "http" / "authorize-response.json"
            _write_json(files["http/authorize-response.json"], allow_resp)
            files["trace-export.json"] = out / "trace-export.json"
            _write_json(files["trace-export.json"], trace_export)
            files["evidence-bundle.json"] = out / "evidence-bundle.json"
            _write_json(files["evidence-bundle.json"], bundle.model_dump(mode="json"))

            # regression-suite.yaml: both decisions pinned, next to policies.yaml
            suite = out / "regression-suite.yaml"
            if suite.exists():
                suite.unlink()
            h = str(home.path)
            for tid, name in (
                (allow_req["trace_id"], "write allowed"),
                (deny_req["trace_id"], "delete denied"),
            ):
                code, _ = _run_cli(
                    "regression", "add", tid, "--suite", str(suite), "--home", h, "--name", name
                )
                assert code == 0, (tid, code)
            data = yaml.safe_load(suite.read_text(encoding="utf-8"))
            data["policies"] = "policies.yaml"
            suite.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            files["regression-suite.yaml"] = suite

            cli: dict[str, tuple[str, ...]] = {
                "trace-list": ("trace", "list", "--json", "--home", h),
                "policy-explain": (
                    "policy",
                    "explain",
                    deny_req["trace_id"],
                    "--json",
                    "--home",
                    h,
                ),
                "policy-impact": (
                    "policy",
                    "impact",
                    "--from",
                    "notes-v1",
                    "--to",
                    "notes-v2",
                    "--suite",
                    str(suite),
                    "--json",
                ),
            }
            for name, argv in cli.items():
                code, stdout = _run_cli(*argv)
                assert code == 0, (name, code)
                files[f"cli-json/{name}.json"] = out / "cli-json" / f"{name}.json"
                _write_json(files[f"cli-json/{name}.json"], json.loads(stdout))
            report = work / "test-report.json"
            code, _ = _run_cli("test", str(suite), "--json", str(report), "--quiet")
            assert code == 0, ("test", code)
            files["cli-json/test.json"] = out / "cli-json" / "test.json"
            _write_json(files["cli-json/test.json"], json.loads(report.read_text(encoding="utf-8")))

            files["reason-codes.txt"] = out / "reason-codes.txt"
            files["reason-codes.txt"].write_text(
                "".join(f"{c}\n" for c in sorted(r.value for r in ReasonCode)), encoding="utf-8"
            )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return files


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if os.environ.get("PYTHONHASHSEED") != "0":
        # Set iteration order (e.g. capability sets) depends on the hash seed.
        os.execve(
            sys.executable,
            [sys.executable, str(Path(__file__).resolve()), *args],
            {**os.environ, "PYTHONHASHSEED": "0"},
        )
    out = Path(args[0]) if args else DEFAULT_OUT
    for name in sorted(generate(out)):
        print(f"wrote {out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
