"""Run the accounts-payable demo.

python -m finance_agent                      # injection scenario, in-process gateway
python -m finance_agent --scenario normal
python -m finance_agent --gateway http://127.0.0.1:8000
ANTHROPIC_API_KEY=... python -m finance_agent --brain anthropic
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from atp_adapter_http import TrustPlaneClient
from finance_agent.agent import AgentBrain, AnthropicAgent, SimulatedAgent
from finance_agent.invoices import (
    INJECTED_INVOICE,
    LEGITIMATE_INVOICE,
    UNDER_LIMIT_INJECTED_INVOICE,
    Invoice,
)
from finance_agent.runner import run_accounts_payable
from finance_agent.scenario import AP_AGENT, HUMAN, seed_delegation_graph

SCENARIOS: dict[str, Invoice] = {
    "normal": LEGITIMATE_INVOICE,
    "injection": INJECTED_INVOICE,
    "under-limit-injection": UNDER_LIMIT_INJECTED_INVOICE,
}


def _make_client(gateway: str | None) -> TrustPlaneClient:
    if gateway:
        return TrustPlaneClient(gateway)
    from atp_gateway import GatewaySettings, create_app

    return TrustPlaneClient.for_app(create_app(GatewaySettings(database_path=":memory:")))


def _make_brain(kind: str) -> AgentBrain:
    if kind == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is required for --brain anthropic")
        return AnthropicAgent()
    return SimulatedAgent()


def main() -> None:
    parser = argparse.ArgumentParser(prog="finance-agent")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="injection")
    parser.add_argument("--gateway", help="Gateway URL. Omit to run an in-process gateway.")
    parser.add_argument("--brain", choices=["simulated", "anthropic"], default="simulated")
    parser.add_argument("--policy-set", default=None, help="e.g. payments-v1 or payments-v2")
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON")
    args = parser.parse_args()

    client = _make_client(args.gateway)
    graph = seed_delegation_graph(client)
    result = run_accounts_payable(
        client,
        _make_brain(args.brain),
        SCENARIOS[args.scenario],
        principal=HUMAN,
        agent=AP_AGENT,
        delegation_grant_id=graph.accounts_payable,
        policy_set_version=args.policy_set,
    )
    if args.json:
        print(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        print(f"Scenario: {args.scenario}   Brain: {args.brain}\n")
        print(result.decision_block())
        print(f"\nLedger entries: {len(client.ledger())}")


if __name__ == "__main__":
    main()
