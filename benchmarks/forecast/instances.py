from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from benchmarks.forecast.baselines import theil_sen_change
from benchmarks.forecast.data import Account
from geostats.stats.forecast import enough_history
from geostats.stats.forecast_features import FEATURES, Floats, features

DAY = 86400.0
MAX_STALENESS_DAYS = 3.0
TARGET_WINDOW_DAYS = 1.5

Series = Literal["overall", "moving", "nomove", "nmpz"]


@dataclass(frozen=True, slots=True)
class Instances:
    accounts: NDArray[np.str_]
    origins: Floats
    target_times: Floats
    current: Floats
    actual: Floats  # rating change from the origin snapshot to the target
    features: Floats
    theil_sen: Floats  # change predicted by the trend baseline

    def __len__(self) -> int:
        return int(self.actual.size)

    def where(self, mask: NDArray[np.bool_]) -> Instances:
        return Instances(
            self.accounts[mask],
            self.origins[mask],
            self.target_times[mask],
            self.current[mask],
            self.actual[mask],
            self.features[mask],
            self.theil_sen[mask],
        )


def weekly_origins(first: datetime, until: datetime) -> list[float]:
    moments: list[float] = []
    moment = first
    while moment < until:
        moments.append(moment.timestamp())
        moment += timedelta(days=7)
    return moments


def build(
    accounts: dict[str, Account], series: Series, horizon: int, origins: list[float]
) -> Instances:
    """One instance per account and origin where the history is long enough
    and the rating is known again about `horizon` days later."""
    ids: list[str] = []
    rows: list[tuple[float, float, float, float, float]] = []
    vectors: list[Floats] = []
    for account_id, account in accounts.items():
        history = account.history(series)
        times = history.times
        for origin in origins:
            k = int(np.searchsorted(times, origin, side="right"))
            if k == 0 or origin - times[k - 1] > MAX_STALENESS_DAYS * DAY:
                continue
            gaps = np.abs(times - (times[k - 1] + horizon * DAY))
            j = int(np.argmin(gaps))
            if j < k or gaps[j] > TARGET_WINDOW_DAYS * DAY or not enough_history(times[:k]):
                continue
            current = float(history.ratings[k - 1])
            ids.append(account_id)
            rows.append(
                (
                    origin,
                    float(times[j]),
                    current,
                    float(history.ratings[j]) - current,
                    float(theil_sen_change(times[:k], history.ratings[:k], horizon)),
                )
            )
            vectors.append(features(history.until(k)))
    table = np.array(rows, dtype=np.float64).reshape(-1, 5)
    return Instances(
        accounts=np.array(ids, dtype=np.str_),
        origins=table[:, 0],
        target_times=table[:, 1],
        current=table[:, 2],
        actual=table[:, 3],
        features=np.array(vectors, dtype=np.float64).reshape(-1, len(FEATURES)),
        theil_sen=table[:, 4],
    )
