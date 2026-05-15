from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from geostats.models import RatingSnapshot
from geostats.stats import _FIELD_ATTR

_MIN_POINTS = 5
_MIN_SPAN_DAYS = 7
_MIN_SIGMA_DAYS = 3
_MAX_DAILY_DELTA = 150           # hard cap on slope contribution per day
_RIDGE_ALPHA = 1.0               # light L2 — recency weighting carries most of the regularisation
_RECENCY_HALF_LIFE_DAYS = 10.0   # exponential decay on sample weights
_SIGMA_WINDOW_DAYS = 30.0        # only recent volatility informs the interval
_MAD_TO_SIGMA = 1.4826           # MAD → robust std for Gaussian-ish noise


@dataclass(frozen=True, slots=True)
class ForecastResult:
    horizon_days: int
    predicted_delta: int | None
    predicted_rating: int | None
    confidence: int | None
    n_points: int


def _sigma_daily_mad(
    times: np.ndarray,
    ratings: np.ndarray,
    window_days: float | None,
) -> float:
    """Robust daily-volatility estimate.

    Collapses snapshots to last-rating-per-UTC-day so intraday polling does
    not inflate variance, then takes MAD of per-day deltas (gap-normalised).
    Returns 0.0 if fewer than _MIN_SIGMA_DAYS distinct days are available.
    """
    cutoff = times[-1] - window_days * 86400.0 if window_days is not None else -np.inf
    day_buckets: dict[int, float] = {}
    for t, r in zip(times, ratings, strict=True):
        if t >= cutoff:
            day_buckets[int(t // 86400)] = float(r)
    if len(day_buckets) < _MIN_SIGMA_DAYS:
        return 0.0
    sorted_days = sorted(day_buckets.keys())
    days_arr = np.array(sorted_days, dtype=np.float64)
    ratings_daily = np.array([day_buckets[d] for d in sorted_days], dtype=np.float64)
    gaps_days = np.diff(days_arr)
    daily_deltas = np.diff(ratings_daily) / np.maximum(gaps_days, 1.0)
    if daily_deltas.size < _MIN_SIGMA_DAYS - 1:
        return 0.0
    med = float(np.median(daily_deltas))
    mad = float(np.median(np.abs(daily_deltas - med)))
    return _MAD_TO_SIGMA * mad


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

    origin = times[0]
    X_days = ((times - origin) / 86400.0).reshape(-1, 1)

    scaler = StandardScaler()
    X_sc = scaler.fit_transform(X_days)

    # Exponential recency weights — recent snapshots dominate the slope.
    elapsed_days = (times[-1] - times) / 86400.0
    sample_weight = np.power(0.5, elapsed_days / _RECENCY_HALF_LIFE_DAYS)

    model = Ridge(alpha=_RIDGE_ALPHA)
    model.fit(X_sc, ratings, sample_weight=sample_weight)

    target_days = np.array([[(times[-1] - origin) / 86400.0 + horizon_days]])
    target_sc = scaler.transform(target_days)
    predicted_raw = float(model.predict(target_sc)[0])
    current = float(ratings[-1])
    max_hist = float(np.max(ratings))

    # Clamp absolute delta so a freak slope can't fly off into orbit.
    max_delta = float(_MAX_DAILY_DELTA * horizon_days)
    clamped_delta = float(np.clip(predicted_raw - current, -max_delta, max_delta))

    # Ceiling: 8% above all-time high; floor: 0
    ceiling = max_hist * 1.08
    predicted_rating = int(round(float(np.clip(current + clamped_delta, 0.0, ceiling))))
    predicted_delta = predicted_rating - int(round(current))

    # Interval: random-walk style with robust per-day sigma over the recent window.
    # Fall back to the full history if the recent window is too sparse.
    sigma_daily = _sigma_daily_mad(times, ratings, _SIGMA_WINDOW_DAYS)
    if sigma_daily <= 0.0:
        sigma_daily = _sigma_daily_mad(times, ratings, None)
    confidence = int(round(sigma_daily * float(np.sqrt(float(horizon_days)))))

    return ForecastResult(
        horizon_days=horizon_days,
        predicted_delta=predicted_delta,
        predicted_rating=predicted_rating,
        confidence=confidence,
        n_points=n,
    )
