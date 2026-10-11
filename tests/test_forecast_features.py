import numpy as np
import pytest

from geostats.stats.forecast_features import FEATURES, History, features

DAY = 86400.0


def _history(ratings: list[float], games: list[float] | None = None) -> History:
    n = len(ratings)
    played = np.array(games if games is not None else [100.0 + 10 * i for i in range(n)])
    return History(
        times=np.arange(n, dtype=np.float64) * DAY,
        ratings=np.array(ratings, dtype=np.float64),
        games_played=played,
        games_won=played / 2,
        win_streak=np.full(n, 3.0),
        guessed_first_rate=np.full(n, 0.5),
        avg_guess_distance_km=np.full(n, 800.0),
    )


def _named(history: History) -> dict[str, float]:
    return dict(zip(FEATURES, features(history), strict=True))


def test_there_are_nineteen_features() -> None:
    assert len(FEATURES) == 19
    assert features(_history([1000.0] * 10)).shape == (19,)


def test_changes_are_measured_against_the_rating_that_many_days_ago() -> None:
    f = _named(_history([1000.0 + 10 * i for i in range(40)]))
    assert f["rating"] == 1390.0
    assert f["change_3d"] == 30.0
    assert f["change_7d"] == 70.0
    assert f["change_30d"] == 300.0


def test_a_short_history_measures_change_against_its_first_snapshot() -> None:
    f = _named(_history([1000.0, 1010.0, 1030.0]))
    assert f["change_30d"] == 30.0


def test_distance_to_peak_low_and_mean() -> None:
    f = _named(_history([1000.0, 1200.0, 1100.0]))
    assert f["below_peak"] == -100.0
    assert f["above_low"] == 100.0
    assert f["above_mean"] == pytest.approx(0.0)
    assert f["above_mean_7d"] == pytest.approx(0.0)


def test_games_in_window_and_win_rate() -> None:
    f = _named(_history([1000.0] * 10))
    assert f["games_7d"] == 70.0
    assert f["games_30d"] == 90.0
    assert f["win_rate"] == 0.5
    assert f["log_games"] == pytest.approx(np.log1p(190.0))


def test_missing_stats_stay_missing() -> None:
    f = _named(_history([1000.0] * 5, games=[float("nan")] * 5))
    assert np.isnan(f["games_7d"])
    assert np.isnan(f["win_rate"])
    assert f["rating"] == 1000.0


def test_features_ignore_snapshots_after_the_cut() -> None:
    full = _history([1000.0 + ((i * 37) % 90) for i in range(30)])
    longer = _history([1000.0 + ((i * 37) % 90) for i in range(30)] + [5000.0, 10.0])
    np.testing.assert_array_equal(features(full), features(longer.until(30)))
