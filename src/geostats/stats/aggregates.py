from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from geostats.models import Account, RatingSnapshot
from geostats.stats import _FIELD_ATTR

_MIN_SNAPS_FOR_AVG = 2

RATING_FIELDS = ("overall", "moving", "nomove", "nmpz")


@dataclass(frozen=True, slots=True)
class Record:
    value: int
    captured_at: datetime


# All functions below require `snaps` sorted ascending by `captured_at`.
def current_rating(
    snaps: list[RatingSnapshot], field: Literal["overall", "moving", "nomove", "nmpz"]
) -> int | None:
    attr = _FIELD_ATTR[field]
    for snap in reversed(snaps):
        v: int | None = getattr(snap, attr)
        if v is not None:
            return v
    return None


def delta_over_period(
    snaps: list[RatingSnapshot],
    field: Literal["overall", "moving", "nomove", "nmpz"],
    *,
    now: datetime,
    window: timedelta,
) -> int | None:
    attr = _FIELD_ATTR[field]
    cutoff = now - window
    if not snaps:
        return None
    latest_snap = snaps[-1]
    latest: int | None = getattr(latest_snap, attr)
    if latest is None:
        return None
    at_cutoff: int | None = None
    for snap in snaps:
        if snap.captured_at <= cutoff:
            v = getattr(snap, attr)
            if v is not None:
                at_cutoff = v
        else:
            break
    if at_cutoff is None:
        return None
    return latest - at_cutoff


def record(
    snaps: list[RatingSnapshot], field: Literal["overall", "moving", "nomove", "nmpz"]
) -> Record | None:
    attr = _FIELD_ATTR[field]
    best: Record | None = None
    for snap in snaps:
        v = getattr(snap, attr)
        if v is not None and (best is None or v > best.value):
            best = Record(value=v, captured_at=snap.captured_at)
    return best


def average_rate_per_week(
    snaps: list[RatingSnapshot],
    field: Literal["overall", "moving", "nomove", "nmpz"],
    *,
    now: datetime,
    window: timedelta,
) -> float | None:
    attr = _FIELD_ATTR[field]
    cutoff = now - window
    in_window = [s for s in snaps if s.captured_at >= cutoff]
    if len(in_window) < _MIN_SNAPS_FOR_AVG:
        return None
    first_val: int | None = None
    for snap in in_window:
        v = getattr(snap, attr)
        if v is not None:
            first_val = v
            break
    last_val: int | None = None
    for snap in reversed(in_window):
        v = getattr(snap, attr)
        if v is not None:
            last_val = v
            break
    if first_val is None or last_val is None:
        return None
    days = window.total_seconds() / 86400
    return (last_val - first_val) / days * 7


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    account: Account
    snaps: list[RatingSnapshot]
    current: dict[str, int | None]
    delta_7d: dict[str, int | None]
    delta_30d: dict[str, int | None]
    record: dict[str, Record | None]
    avg_per_week_30d: dict[str, float | None]
    percentile: dict[str, float | None]


def summarize_profile(
    account: Account,
    snaps: list[RatingSnapshot],
    total_tracked: int = 0,
) -> ProfileSummary:
    now = datetime.now(tz=timezone.utc)  # noqa: UP017
    w7 = timedelta(days=7)
    w30 = timedelta(days=30)
    latest = snaps[-1] if snaps else None
    pct: dict[str, float | None] = {}
    for f in RATING_FIELDS:
        pos: int | None = getattr(latest, f"position_{f}") if latest else None
        if pos is not None and total_tracked > 0:
            pct[f] = round((1 - pos / total_tracked) * 100, 1)
        else:
            pct[f] = None
    return ProfileSummary(
        account=account,
        snaps=snaps,
        current={
            f: current_rating(snaps, f)  # type: ignore[arg-type]
            for f in RATING_FIELDS
        },
        delta_7d={
            f: delta_over_period(snaps, f, now=now, window=w7)  # type: ignore[arg-type]
            for f in RATING_FIELDS
        },
        delta_30d={
            f: delta_over_period(snaps, f, now=now, window=w30)  # type: ignore[arg-type]
            for f in RATING_FIELDS
        },
        record={
            f: record(snaps, f)  # type: ignore[arg-type]
            for f in RATING_FIELDS
        },
        avg_per_week_30d={
            f: average_rate_per_week(snaps, f, now=now, window=w30)  # type: ignore[arg-type]
            for f in RATING_FIELDS
        },
        percentile=pct,
    )
