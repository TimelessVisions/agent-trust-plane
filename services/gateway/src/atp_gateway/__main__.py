"""``python -m atp_gateway`` starts the gateway with uvicorn.

``python -m atp_gateway keygen`` prints fresh keys in ``.env`` form.
"""

from __future__ import annotations

import argparse
import logging
import secrets
import sys

import uvicorn

from atp_gateway.app import create_app
from atp_gateway.settings import GatewaySettings


def keygen() -> None:
    print("# paste into .env (never commit that file)")
    print(f"ATP_GRANT_SIGNING_KEY={secrets.token_urlsafe(48)}")
    print(f"ATP_OPERATOR_KEY={secrets.token_urlsafe(48)}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "keygen":
        keygen()
        return
    parser = argparse.ArgumentParser(prog="atp-gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper())
    uvicorn.run(
        create_app(GatewaySettings()), host=args.host, port=args.port, log_level=args.log_level
    )


if __name__ == "__main__":
    main()
