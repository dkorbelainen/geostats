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
_MAX_DAILY_DELTA = 150  # hard cap on slope contribution per day
_RIDGE_ALPHA = 5.0      # L2 — shrinks aggressive slopes; effect scales with 1/n


@dataclass(frozen=True, slots=True)
class ForecastResult:
    horizon_days: int
    predicted_delta: int | None
    predicted_rating: int | None
    confidence: int | None
    n_points: int


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

    model = Ridge(alpha=_RIDGE_ALPHA)
    model.fit(X_sc, ratings)

    target_days = np.array([[(times[-1] - origin) / 86400.0 + horizon_days]])
    target_sc = scaler.transform(target_days)
    predicted_raw = float(model.predict(target_sc)[0])
    current = float(ratings[-1])
    max_hist = float(np.max(ratings))

    # Clamp delta so slope can't extrapolate beyond _MAX_DAILY_DELTA per day.
    # Apply sqrt dampening for long horizons — growth doesn't scale linearly.
    max_delta = float(_MAX_DAILY_DELTA * horizon_days)
    raw_delta = float(np.clip(predicted_raw - current, -max_delta, max_delta))
    if horizon_days > 7:
        raw_delta *= float(np.sqrt(7.0 / horizon_days))
    clamped_delta = raw_delta

    # Ceiling: 8% above all-time high; floor: 0
    ceiling = max_hist * 1.08
    predicted_rating = int(round(float(np.clip(current + clamped_delta, 0.0, ceiling))))
    predicted_delta = predicted_rating - int(round(current))

    # Random-walk model: uncertainty = sigma_daily * sqrt(horizon).
    # Regression residuals on levels inflate std by sqrt(n) — wrong for ELO-style processes.
    day_gaps = np.diff(times) / 86400.0
    daily_deltas = np.diff(ratings) / np.maximum(day_gaps, 0.5)
    sigma_daily = float(np.std(daily_deltas, ddof=1)) if len(daily_deltas) >= 2 else 0.0
    confidence = int(round(sigma_daily * float(np.sqrt(float(horizon_days)))))

    return ForecastResult(
        horizon_days=horizon_days,
        predicted_delta=predicted_delta,
        predicted_rating=predicted_rating,
        confidence=confidence,
        n_points=n,
    )
