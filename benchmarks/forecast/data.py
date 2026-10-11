from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from geostats.stats.forecast_features import Floats, History

SERIES: dict[str, str] = {
    "overall": "rating",
    "moving": "rating_moving",
    "nomove": "rating_nomove",
    "nmpz": "rating_nmpz",
}
_STATS = ("games_played", "games_won", "win_streak", "guessed_first_rate", "avg_guess_distance_km")


@dataclass(frozen=True, slots=True)
class Account:
    times: Floats
    ratings: dict[str, Floats]
    stats: dict[str, Floats]

    def history(self, series: str) -> History:
        """Snapshots that carry a rating for the series."""
        rated = ~np.isnan(self.ratings[series])
        return History(
            self.times[rated],
            self.ratings[series][rated],
            *(self.stats[name][rated] for name in _STATS),
        )


def _number(raw: str) -> float:
    return float(raw) if raw else float("nan")


def load(path: Path, since: datetime, until: datetime) -> dict[str, Account]:
    """Read an export, keeping snapshots captured in [since, until)."""
    rows: dict[str, list[tuple[float, ...]]] = {}
    with gzip.open(path, "rt", newline="") as handle:
        for row in csv.DictReader(handle):
            captured = datetime.fromisoformat(row["captured_at"])
            if not since <= captured < until:
                continue
            rows.setdefault(row["account_id"], []).append(
                (
                    captured.timestamp(),
                    *(_number(row[column]) for column in SERIES.values()),
                    *(_number(row[name]) for name in _STATS),
                )
            )
    accounts: dict[str, Account] = {}
    for account_id, values in rows.items():
        table = np.array(sorted(values), dtype=np.float64)
        accounts[account_id] = Account(
            times=table[:, 0],
            ratings={name: table[:, 1 + i] for i, name in enumerate(SERIES)},
            stats={name: table[:, 1 + len(SERIES) + i] for i, name in enumerate(_STATS)},
        )
    return accounts
