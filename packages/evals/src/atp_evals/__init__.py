"""Adversarial evaluation harness for the trust plane."""

from atp_evals.harness import EvalContext, EvalScenario
from atp_evals.model import Check, EvalReport, EvalResult, EvalStatus
from atp_evals.runner import format_report, run_scenario, run_suite, run_suite_in_process
from atp_evals.scenarios import SCENARIOS

__all__ = [
    "SCENARIOS",
    "Check",
    "EvalContext",
    "EvalReport",
    "EvalResult",
    "EvalScenario",
    "EvalStatus",
    "format_report",
    "run_scenario",
    "run_suite",
    "run_suite_in_process",
]
