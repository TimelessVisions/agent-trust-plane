from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    """Timezone-aware current time. All timestamps in the system are UTC."""
    return datetime.now(tz=UTC)


def in_seconds(seconds: float) -> datetime:
    return utcnow() + timedelta(seconds=seconds)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
