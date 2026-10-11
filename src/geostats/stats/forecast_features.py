from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

_DAY = 86400.0
_CHANGE_WINDOWS = (3, 7, 14, 30)
_MEAN_WINDOWS = (7, 14, 30)

FEATURES: tuple[str, ...] = (
    "rating",
    *(f"change_{d}d" for d in _CHANGE_WINDOWS),
    *(f"above_mean_{d}d" for d in _MEAN_WINDOWS),
    "below_peak",
    "above_low",
    "above_mean",
    "volatility_30d",
    "games_7d",
    "games_30d",
    "log_games",
    "win_rate",
    "win_streak",
    "guessed_first_rate",
    "avg_guess_distance_km",
)

Floats = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class History:
    """One account's snapshots in ascending time order; NaN marks a missing stat."""

    times: Floats
    ratings: Floats
    games_played: Floats
    games_won: Floats
    win_streak: Floats
    guessed_first_rate: Floats
    avg_guess_distance_km: Floats

    def until(self, k: int) -> History:
        return History(
            self.times[:k],
            self.ratings[:k],
            self.games_played[:k],
            self.games_won[:k],
            self.win_streak[:k],
            self.guessed_first_rate[:k],
            self.avg_guess_distance_km[:k],
        )


def _value_at(times: Floats, values: Floats, moment: float) -> float:
    """Last value at or before the moment, or the earliest one."""
    k = int(np.searchsorted(times, moment, side="right"))
    return float(values[max(k - 1, 0)])


def features(history: History) -> Floats:
    """Feature vector as of the last snapshot; uses nothing after it."""
    t = history.times
    r = history.ratings
    now = float(t[-1])
    current = float(r[-1])
    games = history.games_played
    last_games = float(games[-1])
    recent = r[t >= now - 30 * _DAY]
    values = [
        current,
        *(current - _value_at(t, r, now - d * _DAY) for d in _CHANGE_WINDOWS),
        *(current - float(r[t >= now - d * _DAY].mean()) for d in _MEAN_WINDOWS),
        current - float(r.max()),
        current - float(r.min()),
        current - float(r.mean()),
        float(recent.std()) if recent.size > 1 else 0.0,
        last_games - _value_at(t, games, now - 7 * _DAY),
        last_games - _value_at(t, games, now - 30 * _DAY),
        float(np.log1p(last_games)),
        float(history.games_won[-1]) / last_games if last_games > 0 else float("nan"),
        float(history.win_streak[-1]),
        float(history.guessed_first_rate[-1]),
        float(history.avg_guess_distance_km[-1]),
    ]
    return np.array(values, dtype=np.float64)
