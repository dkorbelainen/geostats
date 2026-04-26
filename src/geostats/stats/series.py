from datetime import UTC, datetime, timedelta
from typing import Literal

from geostats.models import RatingSnapshot

_FIELD_ATTR: dict[str, str] = {
    "overall": "rating",
    "moving": "rating_moving",
    "nomove": "rating_nomove",
    "nmpz": "rating_nmpz",
}

_RANGE_DAYS: dict[str, int | None] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "all": None,
}


def get_series(
    snaps: list[RatingSnapshot],
    field: Literal["overall", "moving", "nomove", "nmpz"],
    range_str: Literal["7d", "30d", "90d", "all"],
) -> list[tuple[str, int]]:
    # snaps must be sorted ascending by captured_at
    attr = _FIELD_ATTR[field]
    days = _RANGE_DAYS[range_str]
    filtered = snaps
    if days is not None:
        cutoff = datetime.now(tz=UTC) - timedelta(days=days)
        filtered = [s for s in snaps if s.captured_at >= cutoff]
    result: list[tuple[str, int]] = []
    for snap in filtered:
        v = getattr(snap, attr)
        if v is not None:
            result.append((snap.captured_at.date().isoformat(), v))
    return result
