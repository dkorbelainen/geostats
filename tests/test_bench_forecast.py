import gzip
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from benchmarks.forecast.baselines import theil_sen_change
from benchmarks.forecast.data import Account, load
from benchmarks.forecast.evaluate import direction_accuracy, mae_difference, summarize
from benchmarks.forecast.instances import build, weekly_origins
from benchmarks.forecast.train import (
    criteria,
    cross_validate,
    fit_gbr,
    fit_named,
    fit_ridge,
    select,
)

from geostats.stats.forecast_features import FEATURES
from geostats.stats.forecast_model import predict

DAY = 86400.0
START = datetime(2026, 7, 1, tzinfo=UTC)
HEADER = (
    "account_id,captured_at,rating,rating_moving,rating_nomove,rating_nmpz,"
    "games_played,games_won,win_streak,guessed_first_rate,avg_guess_distance_km"
)


def _account(ratings: list[float], step_days: float = 1.0) -> Account:
    n = len(ratings)
    series = np.array(ratings, dtype=np.float64)
    return Account(
        times=START.timestamp() + np.arange(n) * step_days * DAY,
        ratings={"overall": series, "moving": series, "nomove": series, "nmpz": series},
        stats={
            "games_played": 100.0 + np.arange(n),
            "games_won": 50.0 + np.arange(n) / 2,
            "win_streak": np.ones(n),
            "guessed_first_rate": np.full(n, 0.5),
            "avg_guess_distance_km": np.full(n, 900.0),
        },
    )


def _export(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "snapshots.csv.gz"
    with gzip.open(path, "wt") as handle:
        handle.write("\n".join([HEADER, *lines]) + "\n")
    return path


def test_load_keeps_the_requested_period_and_marks_missing_values(tmp_path: Path) -> None:
    path = _export(
        tmp_path,
        [
            "a,2026-06-30 23:00:00+00,900,,,,10,5,1,0.5,800",
            "a,2026-07-02 10:00:00+00,1000,,,1100,,,2,0.5,800",
            "a,2026-07-01 10:00:00+00,990,980,,,20,9,2,0.5,800",
            "a,2026-07-05 10:00:00+00,1010,,,,30,9,2,0.5,800",
        ],
    )
    accounts = load(path, START, datetime(2026, 7, 5, tzinfo=UTC))
    account = accounts["a"]
    assert account.ratings["overall"].tolist() == [990.0, 1000.0]
    assert np.isnan(account.stats["games_played"][1])
    assert account.history("nmpz").ratings.tolist() == [1100.0]


def test_weekly_origins_stop_before_the_end() -> None:
    origins = weekly_origins(START, START + timedelta(days=15))
    assert origins == [START.timestamp() + 7 * DAY * i for i in range(3)]


def test_an_instance_pairs_the_origin_snapshot_with_the_one_a_horizon_later() -> None:
    account = _account([1000.0 + 10 * i for i in range(30)])
    origin = START.timestamp() + 10.5 * DAY
    instances = build({"a": account}, "overall", 7, [origin])
    assert len(instances) == 1
    assert instances.current[0] == 1100.0
    assert instances.actual[0] == 70.0
    assert instances.target_times[0] == START.timestamp() + 17 * DAY
    assert instances.features.shape == (1, len(FEATURES))
    assert instances.theil_sen[0] > 0


def test_no_instance_without_a_fresh_snapshot_a_target_or_enough_history() -> None:
    account = _account([1000.0 + 10 * i for i in range(30)])
    first = START.timestamp()
    stale = build({"a": _account([1000.0] * 12)}, "overall", 7, [first + 20 * DAY])
    no_target = build({"a": account}, "overall", 7, [first + 27 * DAY])
    too_short = build({"a": account}, "overall", 7, [first + 3.5 * DAY])
    assert (len(stale), len(no_target), len(too_short)) == (0, 0, 0)


def test_summary_on_known_errors() -> None:
    result = summarize(np.array([10.0, -10.0, 0.0]), np.array([0.0, -40.0, 5.0]))
    assert result["mae"] == pytest.approx(15.0)
    assert result["median_ae"] == 10.0
    assert result["rmse"] == pytest.approx(np.sqrt((100 + 900 + 25) / 3))


def test_direction_ignores_zero_changes() -> None:
    predicted = np.array([5.0, -5.0, 0.0, 5.0])
    actual = np.array([1.0, 1.0, 1.0, 0.0])
    assert direction_accuracy(predicted, actual) == 0.5


def test_mae_difference_is_negative_when_the_prediction_is_closer() -> None:
    rng = np.random.default_rng(1)
    actual = rng.normal(0, 50, 400)
    groups = np.array([f"g{i % 80}" for i in range(400)])
    diff, low, high = mae_difference(actual * 0.5, np.zeros(400), actual, groups)
    assert diff == pytest.approx(-0.5 * np.abs(actual).mean())
    assert low < diff < high < 0
    assert mae_difference(actual * 0.5, np.zeros(400), actual, groups) == (diff, low, high)


def test_ridge_wins_only_within_one_percent_of_the_best() -> None:
    close = {"ridge alpha=1": 10.05, "ridge alpha=10": 10.2, "gbr x": 10.0}
    assert select(close) == "ridge alpha=1"
    assert select({"ridge alpha=1": 10.2, "gbr x": 10.0}) == "gbr x"


def _regression() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    rows = rng.normal(size=(300, len(FEATURES)))
    target = 30 * rows[:, 0] - 20 * (rows[:, 1] > 0) + rng.normal(0, 1, 300)
    rows[rng.random(rows.shape) < 0.05] = np.nan
    groups = np.array([f"g{i % 60}" for i in range(300)])
    return rows, target, groups


def test_exported_boosting_model_predicts_like_scikit_learn() -> None:
    rows, target, _ = _regression()
    medians = np.nanmedian(rows, axis=0)
    filled = np.where(np.isnan(rows), medians, rows)
    for loss in ("absolute_error", "huber"):
        booster = fit_gbr(filled, target, loss, 3)
        model = fit_named(f"gbr {loss} depth=3 trees=300", rows, target)
        np.testing.assert_allclose(predict(model, rows), booster.predict(filled), atol=1e-8)
        fewer = fit_named(f"gbr {loss} depth=3 trees=100", rows, target)
        staged = list(booster.staged_predict(filled))[99]
        np.testing.assert_allclose(predict(fewer, rows), staged, atol=1e-8)


def test_ridge_model_fills_missing_values_and_fits_a_linear_target() -> None:
    rows, target, _ = _regression()
    model = fit_ridge(rows, target, 1.0)
    predicted = predict(model, rows)
    assert not np.isnan(predicted).any()
    assert np.corrcoef(predicted, target)[0, 1] > 0.9


def test_cross_validation_scores_every_candidate() -> None:
    rows, target, groups = _regression()
    scores = cross_validate(rows, target, groups)
    assert len(scores) == 4 + 2 * 2 * 2
    assert all(score > 0 for score in scores.values())


def test_criteria_read_the_interval_bounds() -> None:
    def horizon(high: float, tier_low: float) -> dict[str, object]:
        return {
            "test": {"model_vs_no_change": [-2.0, -3.0, high]},
            "tiers": [{"model_vs_no_change": [0.0, tier_low, 1.0]}],
        }

    passed = criteria({"7": horizon(-1.0, -0.5), "30": horizon(-0.1, 0.0)})
    failed = criteria({"7": horizon(-1.0, -0.5), "30": horizon(0.1, 0.2)})
    assert passed == {
        "beats_no_change_7d": True,
        "beats_no_change_30d": True,
        "no_tier_worse": True,
    }
    assert failed == {
        "beats_no_change_7d": True,
        "beats_no_change_30d": False,
        "no_tier_worse": False,
    }


@pytest.mark.parametrize(
    ("ratings", "week", "month"),
    [
        ([2000.0 + 50 * i for i in range(10)], 175, 196),
        ([2500.0 - 50 * i for i in range(10)], -175, -750),
        ([2000.0] * 10, 0, 0),
        ([1500.0 + (i * 37) % 90 for i in range(40)], -2, -7),
    ],
)
def test_trend_baseline_reproduces_the_forecast_it_replaced(
    ratings: list[float], week: int, month: int
) -> None:
    times = START.timestamp() + np.arange(len(ratings)) * DAY
    series = np.array(ratings)
    assert theil_sen_change(times, series, 7) == week
    assert theil_sen_change(times, series, 30) == month
