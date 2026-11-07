import re
from datetime import UTC, datetime

from fastapi import HTTPException

_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d{1,9})?([Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)
_NO_TIMEZONE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d{1,9})?$")


def parse_rfc3339(value, name: str = "timestamp", status_code: int = 400, assume_utc: bool = False) -> datetime:
    """RFC 3339 string -> naive datetime in UTC, ready for a TIMESTAMP column.
    Raises HTTP status_code (400 by default) if the value is not RFC 3339 or has no timezone designator.
    assume_utc=True also accepts a timestamp without a timezone and reads it as UTC
    (the spec's location-ping examples send "2026-03-14T09:58:20")."""
    if assume_utc and isinstance(value, str) and _NO_TIMEZONE.match(value.strip()):
        value = value.strip() + "Z"
    if not isinstance(value, str) or not _RFC3339.match(value.strip()):
        raise HTTPException(
            status_code=status_code,
            detail=f"{name} must be an RFC 3339 timestamp with a timezone, "
            "e.g. 2026-03-14T15:30:00Z",
        )
    text = value.strip().upper().replace("Z", "+00:00")
    # fromisoformat only takes up to 6 fractional digits on older Pythons
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        return datetime.fromisoformat(text).astimezone(UTC).replace(tzinfo=None)
    except (ValueError, OverflowError):  # impossible date/time, or out of range once moved to UTC
        raise HTTPException(status_code=status_code, detail=f"{name} is not a valid date/time.")


def to_rfc3339(value: datetime | None) -> str | None:
    """datetime from a TIMESTAMP column (stored as UTC) -> '2026-03-14T10:00:00Z'."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += f".{value.microsecond:06d}".rstrip("0")
    return text + "Z"
