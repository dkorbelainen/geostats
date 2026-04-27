from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import scipy.stats
from sklearn.linear_model import LinearRegression

from geostats.models import RatingSnapshot
from geostats.stats import _FIELD_ATTR

_MIN_POINTS = 5


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
    if n < _MIN_POINTS:
        return ForecastResult(
            horizon_days=horizon_days,
            predicted_delta=None,
            predicted_rating=None,
            confidence=None,
            n_points=n,
        )

    times = np.array([p[0] for p in pairs], dtype=np.float64)
    ratings = np.array([p[1] for p in pairs], dtype=np.float64)

    origin = times[0]
    X = (times - origin).reshape(-1, 1)

    model = LinearRegression()
    model.fit(X, ratings)

    target_x = np.array([[times[-1] - origin + horizon_days * 86400.0]])
    predicted = float(model.predict(target_x)[0])
    current = float(ratings[-1])

    residuals = ratings - model.predict(X).ravel()
    std_res = float(np.std(residuals, ddof=1))
    t_crit = float(scipy.stats.t.ppf(0.975, df=n - 2))
    confidence = int(round(abs(std_res * t_crit)))

    return ForecastResult(
        horizon_days=horizon_days,
        predicted_delta=int(round(predicted - current)),
        predicted_rating=int(round(predicted)),
        confidence=confidence,
        n_points=n,
    )
