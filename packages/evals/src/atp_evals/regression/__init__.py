"""Security regression tests: pin authorization decisions and run them in CI."""

from atp_evals.regression.format import (
    SUITE_VERSION,
    CaseSpec,
    DelegationSpec,
    Expectation,
    GrantSpec,
    Source,
    Suite,
    dump_suite,
    load_suite,
)
from atp_evals.regression.record import TraceConversionError, case_from_trace, merge_into_suite
from atp_evals.regression.runner import (
    CaseResult,
    SuiteReport,
    format_text,
    run_suite,
    to_json,
    to_junit,
)

__all__ = [
    "SUITE_VERSION",
    "CaseResult",
    "CaseSpec",
    "DelegationSpec",
    "Expectation",
    "GrantSpec",
    "Source",
    "Suite",
    "SuiteReport",
    "TraceConversionError",
    "case_from_trace",
    "dump_suite",
    "format_text",
    "load_suite",
    "merge_into_suite",
    "run_suite",
    "to_json",
    "to_junit",
]
