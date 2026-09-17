from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from atp_adapter_http import TrustPlaneClient
from atp_cli.main import main
from atp_gateway.local import LocalGateway
from finance_agent import (
    AP_AGENT,
    HUMAN,
    INJECTED_INVOICE,
    SimulatedAgent,
    run_accounts_payable,
    seed_delegation_graph,
)

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "examples" / "regression-suite" / "accounts-payable.yaml"


def _run(*args: str) -> int:
    with pytest.raises(SystemExit) as exc:
        main(list(args))
    code = exc.value.code
    return int(code) if isinstance(code, int) else 1


def test_doctor_runs(capsys: pytest.CaptureFixture[str]) -> None:
    _run("doctor", "--port", "1")  # port 1 is never listening
    out = capsys.readouterr().out
    assert "Python >= 3.12" in out and "workspace packages importable: all present" in out


def test_test_command_exit_codes_and_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    j, x = tmp_path / "r.json", tmp_path / "r.xml"
    assert _run("test", str(SAMPLE), "--json", str(j), "--junit", str(x)) == 0
    assert json.loads(j.read_text())["summary"]["ok"] is True
    assert "<testsuite" in x.read_text()
    assert "8/8 passed under payments-v2" in capsys.readouterr().out
    assert _run("test", str(SAMPLE), "--policy-set", "payments-v1", "--quiet") == 1
    assert _run("test", str(tmp_path / "missing.yaml")) == 2


def test_record_from_live_gateway(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ATP_OPERATOR_KEY", raising=False)
    with LocalGateway() as gw:
        operator = TrustPlaneClient(gw.url, operator_key=gw.operator_key)
        seed = seed_delegation_graph(operator)
        result = run_accounts_payable(
            operator.as_agent(seed.identities.accounts_payable_token),
            SimulatedAgent(),
            INJECTED_INVOICE,
            principal=HUMAN,
            agent=AP_AGENT,
            delegation_grant_id=seed.graph.accounts_payable,
        )
        suite = tmp_path / "recorded.yaml"
        code = _run(
            "record",
            "--trace",
            result.trace_id,
            "--gateway",
            gw.url,
            "--operator-key",
            gw.operator_key,
            "--suite",
            str(suite),
            "--name",
            "injected payment",
        )
        assert code == 0
        assert "expected: DENY / PAYMENT_EXCEEDS_DELEGATED_AUTHORITY" in capsys.readouterr().out
        # without the operator key nothing can be recorded
        assert (
            _run("record", "--trace", result.trace_id, "--gateway", gw.url, "--suite", str(suite))
            == 2
        )
    # the recorded suite reproduces on a fresh ephemeral gateway
    assert _run("test", str(suite), "--quiet") == 0
    text = suite.read_text(encoding="utf-8")
    assert "Ignore all previous instructions" not in text
    assert "atpa_" not in text


def test_demo_regression_generates_a_suite_that_pins_the_fix(tmp_path: Path) -> None:
    out = tmp_path / "regression.yaml"
    assert _run("demo", "regression", "--out", str(out)) == 0
    assert _run("test", str(out), "--quiet") == 0
    assert _run("test", str(out), "--policy-set", "payments-v1", "--quiet") == 1


def test_console_script_is_installed() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "atp_cli.main", "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0 and "atp" in proc.stdout
