from datetime import UTC, datetime, timedelta
from typing import Literal

from geostats.models import RatingSnapshot
from geostats.stats import _FIELD_ATTR

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
    *,
    now: datetime | None = None,
) -> list[tuple[str, int]]:
    # snaps must be sorted ascending by captured_at
    attr = _FIELD_ATTR[field]
    days = _RANGE_DAYS[range_str]
    filtered = snaps
    if days is not None:
        _now = now if now is not None else datetime.now(tz=UTC)
        cutoff = _now - timedelta(days=days)
        filtered = [s for s in snaps if s.captured_at >= cutoff]
    # snaps sorted ascending → later value overwrites earlier for same day
    seen: dict[str, int] = {}
    for snap in filtered:
        v = getattr(snap, attr)
        if v is not None:
            seen[snap.captured_at.date().isoformat()] = v
    return list(seen.items())
