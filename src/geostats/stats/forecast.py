from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from geostats.models import RatingSnapshot
from geostats.stats import _FIELD_ATTR

_MIN_POINTS = 5
_MIN_SPAN_DAYS = 7
_MIN_DAILY_POINTS = 5            # robust slope needs at least this many distinct UTC days
_MIN_PAIRS_FOR_SLOPE = 2         # at least one pair is required for any slope estimate
_WINDOW_DAYS = 30                # only the recent window informs the slope
_MAX_DAILY_DELTA = 150           # hard cap on slope contribution per day
_FULL_CREDIBILITY_DAYS = 20      # at >=20 daily points, slope used at full weight
_PEAK_HEADROOM = 1.08            # forecast can exceed all-time high by at most 8%


@dataclass(frozen=True, slots=True)
class ForecastResult:
    horizon_days: int
    predicted_delta: int | None
    predicted_rating: int | None
    confidence: int | None
    n_points: int


def _daily_series(
    times: np.ndarray,
    ratings: np.ndarray,
    window_days: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Collapse snapshots to one rating per UTC day within the recent window.

    Multiple snapshots per day are common (intraday polling) — using all of
    them lets short bursts dominate the trend. We keep the last rating of
    each UTC day inside the window.
    """
    cutoff = times[-1] - window_days * 86400.0
    buckets: dict[int, float] = {}
    for t, r in zip(times, ratings, strict=True):
        if t >= cutoff:
            buckets[int(t // 86400)] = float(r)
    if len(buckets) < _MIN_DAILY_POINTS:
        # Fall back to whatever we have if the recent window is sparse.
        buckets = {}
        for t, r in zip(times, ratings, strict=True):
            buckets[int(t // 86400)] = float(r)
    days_sorted = sorted(buckets.keys())
    return (
        np.array(days_sorted, dtype=np.float64),
        np.array([buckets[d] for d in days_sorted], dtype=np.float64),
    )


def _theil_sen_slope(days: np.ndarray, ratings: np.ndarray) -> float:
    """Median pairwise slope — robust to outlier sessions.

    Unlike OLS/Ridge, a single noisy day shifts the median by at most one
    pair, so the predicted delta does not swing dramatically as new data
    arrives.
    """
    if days.size < _MIN_PAIRS_FOR_SLOPE:
        return 0.0
    di = days[:, None]
    dj = days[None, :]
    ri = ratings[:, None]
    rj = ratings[None, :]
    mask = dj > di
    if not np.any(mask):
        return 0.0
    slopes = (rj - ri)[mask] / (dj - di)[mask]
    return float(np.median(slopes))


def forecast_rating(
    snaps: list[RatingSnapshot],
    field: Literal["overall", "moving", "nomove", "nmpz"],
    horizon_days: int,
) -> ForecastResult:
    attr = _FIELD_ATTR[field]
    pairs = [
        (s.captured_at.timestamp(), int(getattr(s, attr)))
        for s in snaps
        if getattr(s, attr) is not None
    ]
    n = len(pairs)
    null = ForecastResult(
        horizon_days=horizon_days,
        predicted_delta=None,
        predicted_rating=None,
        confidence=None,
        n_points=n,
    )
    if n < _MIN_POINTS:
        return null

    times = np.array([p[0] for p in pairs], dtype=np.float64)
    ratings = np.array([p[1] for p in pairs], dtype=np.float64)

    span_days = (times[-1] - times[0]) / 86400.0
    if span_days < _MIN_SPAN_DAYS:
        return null

    daily_days, daily_ratings = _daily_series(times, ratings, _WINDOW_DAYS)
    if daily_days.size < _MIN_DAILY_POINTS:
        return null

    slope_per_day = _theil_sen_slope(daily_days, daily_ratings)

    # Credibility shrinkage: small samples get pulled toward zero so the
    # prediction does not commit to a slope estimated from a handful of days.
    credibility = min(1.0, daily_days.size / float(_FULL_CREDIBILITY_DAYS))
    slope_per_day *= credibility

    raw_delta = slope_per_day * float(horizon_days)
    max_delta = float(_MAX_DAILY_DELTA * horizon_days)
    clamped_delta = float(np.clip(raw_delta, -max_delta, max_delta))

    current = float(ratings[-1])
    ceiling = float(np.max(ratings)) * _PEAK_HEADROOM
    predicted_rating = int(round(float(np.clip(current + clamped_delta, 0.0, ceiling))))
    predicted_delta = predicted_rating - int(round(current))

    return ForecastResult(
        horizon_days=horizon_days,
        predicted_delta=predicted_delta,
        predicted_rating=predicted_rating,
        confidence=None,
        n_points=n,
    )
