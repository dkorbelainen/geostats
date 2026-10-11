from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np

from geostats.models import RatingSnapshot
from geostats.stats import _FIELD_ATTR
from geostats.stats.forecast_features import Floats, History, features
from geostats.stats.forecast_model import Model, predict

_DAY = 86400.0
_MIN_POINTS = 5
_MIN_SPAN_DAYS = 7
_MIN_DAYS = 5
# benchmarks/forecast.md: on the other mode ratings the model does not beat "no change"
_FORECAST_FIELDS = frozenset({"overall", "nomove"})
_MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "forecast_model.json"


@dataclass(frozen=True, slots=True)
class ForecastResult:
    horizon_days: int
    predicted_delta: int | None
    predicted_rating: int | None
    confidence: int | None
    n_points: int


@lru_cache
def _models() -> dict[int, Model]:
    stored = json.loads(_MODEL_PATH.read_text())
    return {int(days): model for days, model in stored["horizons"].items()}


def enough_history(times: Floats) -> bool:
    return (
        times.size >= _MIN_POINTS
        and float(times[-1] - times[0]) >= _MIN_SPAN_DAYS * _DAY
        and np.unique(times // _DAY).size >= _MIN_DAYS
    )


def predicted_change(history: History, horizon_days: int) -> float:
    """Rating change `horizon_days` ahead of the last snapshot.

    The models are trained for fixed horizons; days in between are interpolated
    and longer horizons keep the value of the longest one.
    """
    models = _models()
    row = features(history)[None, :]
    days = sorted(models)
    changes = [float(predict(models[d], row)[0]) for d in days]
    return float(np.interp(horizon_days, [0, *days], [0.0, *changes]))


def _stat(snaps: list[RatingSnapshot], name: str) -> Floats:
    values = [getattr(s, name) for s in snaps]
    return np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)


def forecast_rating(
    snaps: list[RatingSnapshot],
    field: Literal["overall", "moving", "nomove", "nmpz"],
    horizon_days: int,
) -> ForecastResult:
    attr = _FIELD_ATTR[field]
    rated = [s for s in snaps if getattr(s, attr) is not None]
    times = np.array([s.captured_at.timestamp() for s in rated], dtype=np.float64)
    if field not in _FORECAST_FIELDS or not enough_history(times):
        return ForecastResult(
            horizon_days=horizon_days,
            predicted_delta=None,
            predicted_rating=None,
            confidence=None,
            n_points=len(rated),
        )
    history = History(
        times,
        _stat(rated, attr),
        _stat(rated, "games_played"),
        _stat(rated, "games_won"),
        _stat(rated, "win_streak"),
        _stat(rated, "guessed_first_rate"),
        _stat(rated, "avg_guess_distance_km"),
    )
    current = int(history.ratings[-1])
    predicted = max(0, int(round(current + predicted_change(history, horizon_days))))
    return ForecastResult(
        horizon_days=horizon_days,
        predicted_delta=predicted - current,
        predicted_rating=predicted,
        confidence=None,
        n_points=len(rated),
    )
