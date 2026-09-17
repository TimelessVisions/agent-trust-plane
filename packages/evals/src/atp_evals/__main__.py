"""Run the adversarial eval suite.

python -m atp_evals                       # in-process gateway
python -m atp_evals --gateway http://127.0.0.1:8000
python -m atp_evals --report eval-reports/latest.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from atp_adapter_http import GatewayError, TrustPlaneClient
from atp_evals.runner import format_report, run_suite


def main() -> None:
    parser = argparse.ArgumentParser(prog="atp-evals")
    parser.add_argument("--gateway", help="Gateway URL. Omit to run an in-process gateway.")
    parser.add_argument("--report", help="Write the JSON report to this path.")
    parser.add_argument(
        "--operator-key",
        default=os.environ.get("ATP_OPERATOR_KEY"),
        help="Operator key of the remote gateway (EVAL-006 selects a policy set). "
        "Defaults to $ATP_OPERATOR_KEY.",
    )
    args = parser.parse_args()

    if args.gateway:
        client = TrustPlaneClient(args.gateway, operator_key=args.operator_key)
    else:
        from atp_gateway import GatewaySettings, create_app

        app = create_app(GatewaySettings(database_path=":memory:"))
        client = TrustPlaneClient.for_app(app, operator_key=app.state.runtime.operator_key)

    with client:
        try:
            report = run_suite(client)
        except GatewayError as exc:
            if exc.reason_code in {"OPERATOR_KEY_REQUIRED", "POLICY_SET_OVERRIDE_FORBIDDEN"}:
                sys.exit(
                    "The eval suite is operator tooling: it issues agent credentials and "
                    "selects policy sets. Pass --operator-key or set ATP_OPERATOR_KEY to the "
                    f"gateway's key. ({exc})"
                )
            raise

    print(format_report(report))
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
        print(f"\nreport written to {path}")
    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
