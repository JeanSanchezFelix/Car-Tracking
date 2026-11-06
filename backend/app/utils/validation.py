import math

from fastapi import HTTPException

MAX_BIGINT = 9223372036854775807


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def require_positive_id(value, name: str, status_code: int = 400) -> int:
    """IDs must be positive integers that fit a BIGINT column."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_BIGINT:
        raise HTTPException(status_code=status_code, detail=f"{name} must be a positive integer.")
    return value


def clean_text(value, name: str, required: bool = False, status_code: int = 400) -> str | None:
    """Trim leading/trailing whitespace. required=True also rejects empty text.
    status_code is the HTTP status used when the value is rejected (400 by default)."""

    def fail(message: str) -> HTTPException:
        return HTTPException(status_code=status_code, detail=message)

    if value is None:
        if required:
            raise fail(f"{name} is required.")
        return None
    if not isinstance(value, str):
        raise fail(f"{name} must be a string.")
    if "\x00" in value:
        raise fail(f"{name} contains invalid characters.")
    value = value.strip()
    if required and not value:
        raise fail(f"{name} is required and must be non-empty.")
    return value


def reject_unknown_fields(payload: dict, allowed) -> None:
    """A JSON body with fields the endpoint does not know is an invalid payload shape (400)."""
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise bad_request(f"Unknown field(s): {', '.join(unknown)}.")


def require_later(start, end, start_name: str, end_name: str, status_code: int = 422) -> None:
    """Time ordering: when both are set, end must be strictly later than start."""
    if start is not None and end is not None and end <= start:
        raise HTTPException(status_code=status_code, detail=f"{end_name} must be later than {start_name}.")


def require_non_negative_int(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_BIGINT:
        raise bad_request(f"{name} must be a non-negative integer.")
    return value


def escape_like(value: str) -> str:
    """Escape %, _ and \\ so user text is matched literally inside a LIKE/ILIKE pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_bbox(raw: str) -> tuple:
    """'minLon,minLat,maxLon,maxLat' -> 4 floats, validated as WGS84 with min < max."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise bad_request("bbox must be four comma-separated numbers: minLon,minLat,maxLon,maxLat.")
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        raise bad_request("bbox values must be numbers.")
    if not all(math.isfinite(n) for n in (min_lon, min_lat, max_lon, max_lat)):
        raise bad_request("bbox values must be finite numbers.")
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise bad_request("bbox longitudes must be between -180 and 180.")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise bad_request("bbox latitudes must be between -90 and 90.")
    if not (min_lon < max_lon and min_lat < max_lat):
        raise bad_request("bbox min values must be less than max values.")
    return min_lon, min_lat, max_lon, max_lat