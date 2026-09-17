from __future__ import annotations

import argparse
import os

from atp_adapter_http import TrustPlaneClient
from atp_adapter_mcp.interceptor import DEFAULT_MAPPINGS, AgentContext, McpInterceptor
from atp_adapter_mcp.server import build_server
from atp_core import PrincipalKind, PrincipalRef


def main() -> None:
    parser = argparse.ArgumentParser(prog="atp-mcp")
    parser.add_argument("--gateway", default="http://127.0.0.1:8000")
    parser.add_argument("--grant", required=True, help="delegation grant id the agent acts under")
    parser.add_argument("--agent", default="accounts-payable-agent")
    parser.add_argument("--principal", default="company-user-42")
    parser.add_argument(
        "--agent-token",
        default=os.environ.get("ATP_AGENT_TOKEN"),
        help="Bearer credential for the agent (defaults to $ATP_AGENT_TOKEN).",
    )
    args = parser.parse_args()

    ctx = AgentContext(
        principal=PrincipalRef(id=args.principal, kind=PrincipalKind.HUMAN),
        agent=PrincipalRef(id=args.agent, kind=PrincipalKind.AGENT),
        delegation_grant_id=args.grant,
    )
    if not args.agent_token:
        parser.error("--agent-token or ATP_AGENT_TOKEN is required")
    client = TrustPlaneClient(args.gateway, agent_token=args.agent_token)
    interceptor = McpInterceptor(client, DEFAULT_MAPPINGS)
    build_server(interceptor, ctx).run(transport="stdio")


if __name__ == "__main__":
    main()
