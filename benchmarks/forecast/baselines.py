"""The trend forecast the site served before the learned model, kept as a baseline."""

from __future__ import annotations

import numpy as np

from geostats.stats.forecast_features import Floats

_DAY = 86400.0
_MIN_DAILY_POINTS = 5
_WINDOW_DAYS = 30
_MAX_DAILY_CHANGE = 150
_FULL_CREDIBILITY_DAYS = 20
_PEAK_HEADROOM = 1.08
_MAX_POINTS = 365


def _daily(times: Floats, ratings: Floats) -> tuple[Floats, Floats]:
    """Last rating of each UTC day in the recent window, or of every day when it is sparse."""
    days = (times // _DAY).astype(np.int64)
    recent = times >= times[-1] - _WINDOW_DAYS * _DAY
    if np.unique(days[recent]).size >= _MIN_DAILY_POINTS:
        days, ratings = days[recent], ratings[recent]
    last_of_day = np.append(days[1:] != days[:-1], True)
    return days[last_of_day].astype(np.float64), ratings[last_of_day]


def _median_slope(days: Floats, ratings: Floats) -> float:
    later = days[None, :] > days[:, None]
    slopes = (ratings[None, :] - ratings[:, None])[later] / (days[None, :] - days[:, None])[later]
    return float(np.median(slopes))


def theil_sen_change(times: Floats, ratings: Floats, horizon: int) -> int:
    """Theil–Sen slope over daily ratings, shrunk for short histories and capped."""
    times, ratings = times[-_MAX_POINTS:], ratings[-_MAX_POINTS:]
    days, daily = _daily(times, ratings)
    slope = _median_slope(days, daily) * min(1.0, days.size / _FULL_CREDIBILITY_DAYS)
    limit = float(_MAX_DAILY_CHANGE * horizon)
    change = float(np.clip(slope * horizon, -limit, limit))
    current = float(ratings[-1])
    ceiling = float(ratings.max()) * _PEAK_HEADROOM
    return int(round(float(np.clip(current + change, 0.0, ceiling)))) - int(round(current))
