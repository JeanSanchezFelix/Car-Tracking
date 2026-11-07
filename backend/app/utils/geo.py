import json

from backend.app.utils.validation import bad_request, is_finite_number


def _check_position(position, name: str) -> None:
    if not (
        isinstance(position, list)
        and len(position) == 2
        and all(is_finite_number(c) for c in position)
    ):
        raise bad_request(f"{name}: every position must be a [longitude, latitude] pair of numbers.")
    lon, lat = position
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise bad_request(
            f"{name}: coordinates out of WGS84 range (longitude -180..180, latitude -90..90)."
        )


def validate_geometry(geom, expected_type: str, name: str = "geom") -> str:
    """expected_type: 'Point', 'LineString' or 'Polygon'. Returns a JSON string."""
    if not isinstance(geom, dict):
        raise bad_request(f"{name} must be a GeoJSON {expected_type} object.")
    if geom.get("type") != expected_type:
        raise bad_request(f"{name} must be a GeoJSON {expected_type}.")
    coords = geom.get("coordinates")

    if expected_type == "Point":
        _check_position(coords, name)
    elif expected_type == "LineString":
        if not isinstance(coords, list) or len(coords) < 2:
            raise bad_request(f"{name}: a LineString needs at least 2 positions.")
        for position in coords:
            _check_position(position, name)
    elif expected_type == "Polygon":
        if not isinstance(coords, list) or not coords:
            raise bad_request(f"{name}: a Polygon needs at least one ring.")
        for ring in coords:
            if not isinstance(ring, list) or len(ring) < 4:
                raise bad_request(f"{name}: each Polygon ring needs at least 4 positions.")
            for position in ring:
                _check_position(position, name)
            if ring[0] != ring[-1]:
                raise bad_request(f"{name}: Polygon rings must be closed (first = last position).")
    else:  # programming error, not a client error
        raise ValueError(f"unsupported geometry type {expected_type}")

    return json.dumps({"type": expected_type, "coordinates": coords})
