from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from geostats.models import RatingSnapshot
from geostats.stats import forecast
from geostats.stats.forecast import forecast_rating
from geostats.stats.forecast_features import FEATURES
from geostats.stats.forecast_model import Model

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)


def _snaps(ratings: list[int], step_hours: float = 24.0) -> list[RatingSnapshot]:
    n = len(ratings)
    return [
        RatingSnapshot(
            account_id="acc1",
            captured_at=NOW - timedelta(hours=step_hours * (n - 1 - i)),
            rating=rating,
            games_played=500 + 5 * i,
            games_won=250 + 2 * i,
            win_streak=2,
            guessed_first_rate=0.5,
            avg_guess_distance_km=900.0,
        )
        for i, rating in enumerate(ratings)
    ]


def _constant(change: float) -> Model:
    zeros = [0.0] * len(FEATURES)
    return {
        "kind": "ridge",
        "medians": zeros,
        "mean": zeros,
        "scale": [1.0] * len(FEATURES),
        "coef": zeros,
        "intercept": change,
    }


@pytest.fixture
def constant_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "_models", lambda: {7: _constant(14.0), 30: _constant(60.0)})


def test_too_few_points_give_no_forecast() -> None:
    result = forecast_rating(_snaps([2000, 2010, 2020, 2030]), "overall", 7)
    assert result.predicted_delta is None
    assert result.predicted_rating is None
    assert result.confidence is None
    assert result.n_points == 4


def test_a_span_under_a_week_gives_no_forecast() -> None:
    assert forecast_rating(_snaps([2000] * 6), "overall", 7).predicted_delta is None


def test_fewer_than_five_days_give_no_forecast() -> None:
    snaps = _snaps([2000] * 4, step_hours=72) + _snaps([2000] * 4, step_hours=1)[1:]
    assert forecast_rating(sorted(snaps, key=lambda s: s.captured_at), "overall", 7).n_points == 7
    assert forecast_rating(snaps, "overall", 7).predicted_delta is None


def test_no_snapshots_give_no_forecast() -> None:
    result = forecast_rating([], "overall", 7)
    assert result.predicted_delta is None
    assert result.n_points == 0


@pytest.mark.usefixtures("constant_models")
def test_the_trained_horizons_use_their_models() -> None:
    snaps = _snaps([2000] * 10)
    week = forecast_rating(snaps, "overall", 7)
    month = forecast_rating(snaps, "overall", 30)
    assert (week.predicted_delta, week.predicted_rating) == (14, 2014)
    assert (month.predicted_delta, month.predicted_rating) == (60, 2060)
    assert week.n_points == 10
    assert week.confidence is None


@pytest.mark.usefixtures("constant_models")
def test_other_horizons_interpolate_and_stop_growing_after_the_longest() -> None:
    snaps = _snaps([2000] * 10)
    assert forecast_rating(snaps, "overall", 1).predicted_delta == 2
    assert forecast_rating(snaps, "overall", 14).predicted_delta == 28
    assert forecast_rating(snaps, "overall", 90).predicted_delta == 60
    assert forecast_rating(snaps, "overall", 90).horizon_days == 90


def test_the_rating_never_goes_below_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "_models", lambda: {7: _constant(-900.0), 30: _constant(-900.0)})
    result = forecast_rating(_snaps([300] * 10), "overall", 7)
    assert (result.predicted_rating, result.predicted_delta) == (0, -300)


@pytest.mark.usefixtures("constant_models")
def test_a_mode_forecast_reads_the_mode_rating() -> None:
    snaps = _snaps([2000] * 10)
    for snap in snaps:
        snap.rating_nomove = 1500
    snaps[0].rating_nomove = None
    result = forecast_rating(snaps, "nomove", 7)
    assert result.predicted_rating == 1514
    assert result.n_points == 9


@pytest.mark.usefixtures("constant_models")
@pytest.mark.parametrize("field", ["moving", "nmpz"])
def test_modes_where_the_model_does_not_help_get_no_forecast(field: str) -> None:
    snaps = _snaps([2000] * 10)
    for snap in snaps:
        snap.rating_moving = snap.rating_nmpz = 1500
    result = forecast_rating(snaps, field, 7)  # type: ignore[arg-type]
    assert result.predicted_delta is None
    assert result.n_points == 10


def test_the_shipped_models_cover_a_week_and_a_month() -> None:
    forecast._models.cache_clear()
    models = forecast._models()
    assert sorted(models) == [7, 30]
    assert all(len(model["medians"]) == len(FEATURES) for model in models.values())


def test_the_shipped_models_answer_on_a_plain_history() -> None:
    ratings = [1500 + (i * 37) % 90 for i in range(40)]
    result = forecast_rating(_snaps(ratings), "overall", 30)
    assert result.predicted_delta is not None
    assert abs(result.predicted_delta) < 400


def test_result_is_frozen() -> None:
    result = forecast_rating(_snaps([2000] * 10), "overall", 7)
    with pytest.raises((AttributeError, TypeError)):
        result.predicted_delta = 999  # type: ignore[misc]


def test_enough_history_needs_points_span_and_days() -> None:
    day = 86400.0
    assert forecast.enough_history(np.arange(8) * day)
    assert not forecast.enough_history(np.arange(4) * 3 * day)
    assert not forecast.enough_history(np.arange(6) * day)
