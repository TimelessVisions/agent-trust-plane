"""Run the adversarial eval suite.

python -m atp_evals                       # in-process gateway
python -m atp_evals --gateway http://127.0.0.1:8000
python -m atp_evals --report eval-reports/latest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atp_adapter_http import TrustPlaneClient
from atp_evals.runner import format_report, run_suite


def main() -> None:
    parser = argparse.ArgumentParser(prog="atp-evals")
    parser.add_argument("--gateway", help="Gateway URL. Omit to run an in-process gateway.")
    parser.add_argument("--report", help="Write the JSON report to this path.")
    args = parser.parse_args()

    if args.gateway:
        client = TrustPlaneClient(args.gateway)
    else:
        from atp_gateway import GatewaySettings, create_app

        client = TrustPlaneClient.for_app(create_app(GatewaySettings(database_path=":memory:")))

    with client:
        report = run_suite(client)

    print(format_report(report))
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
        print(f"\nreport written to {path}")
    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
