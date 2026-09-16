from __future__ import annotations

import logging
import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("atp.gateway")


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATP_", env_file=".env", extra="ignore")

    grant_signing_key: str = Field(
        default="",
        description="HMAC key for execution grants. Empty = ephemeral key generated at startup.",
    )
    grant_ttl_seconds: int = Field(default=120, ge=5, le=3600)
    database_path: str = Field(default="./data/atp.db", description="SQLite path or ':memory:'.")
    cors_origins: str = Field(default="http://localhost:3000")
    default_policy_set: str = Field(default="payments-v2")

    def signing_key_bytes(self) -> bytes:
        if self.grant_signing_key:
            return self.grant_signing_key.encode("utf-8")
        log.warning(
            "ATP_GRANT_SIGNING_KEY is not set; using an ephemeral key. "
            "Execution grants will not survive a restart."
        )
        return secrets.token_bytes(32)

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
