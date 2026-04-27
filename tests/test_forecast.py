from datetime import datetime, timedelta, timezone

import pytest

from geostats.models import RatingSnapshot
from geostats.stats.forecast import forecast_rating


def _now() -> datetime:
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)  # noqa: UP017


def _snaps_rising(n: int = 10) -> list[RatingSnapshot]:
    now = _now()
    return [
        RatingSnapshot(
            account_id="acc1",
            captured_at=now - timedelta(days=n - i),
            rating=2000 + i * 50,
        )
        for i in range(n)
    ]


def _snaps_flat(n: int = 10) -> list[RatingSnapshot]:
    now = _now()
    return [
        RatingSnapshot(
            account_id="acc1",
            captured_at=now - timedelta(days=n - i),
            rating=2000,
        )
        for i in range(n)
    ]


def test_forecast_below_min_points_returns_none_values() -> None:
    snaps = _snaps_rising(4)
    result = forecast_rating(snaps, "overall", 7)
    assert result.predicted_delta is None
    assert result.predicted_rating is None
    assert result.confidence is None
    assert result.n_points == 4


def test_forecast_rising_gives_positive_delta() -> None:
    snaps = _snaps_rising(10)
    result = forecast_rating(snaps, "overall", 7)
    assert result.predicted_delta is not None
    assert result.predicted_delta > 0


def test_forecast_falling_gives_negative_delta() -> None:
    now = _now()
    snaps = [
        RatingSnapshot(
            account_id="acc1",
            captured_at=now - timedelta(days=10 - i),
            rating=2500 - i * 50,
        )
        for i in range(10)
    ]
    result = forecast_rating(snaps, "overall", 7)
    assert result.predicted_delta is not None
    assert result.predicted_delta < 0


def test_forecast_flat_data_near_zero_delta() -> None:
    snaps = _snaps_flat(10)
    result = forecast_rating(snaps, "overall", 7)
    assert result.predicted_delta is not None
    assert abs(result.predicted_delta) < 5


def test_forecast_n_points_counted() -> None:
    snaps = _snaps_rising(8)
    result = forecast_rating(snaps, "overall", 30)
    assert result.n_points == 8


def test_forecast_horizon_days_preserved() -> None:
    snaps = _snaps_rising(10)
    result = forecast_rating(snaps, "overall", 60)
    assert result.horizon_days == 60


def test_forecast_confidence_is_nonnegative() -> None:
    snaps = _snaps_rising(10)
    result = forecast_rating(snaps, "overall", 7)
    assert result.confidence is not None
    assert result.confidence >= 0


def test_forecast_empty_snaps_returns_none_values() -> None:
    result = forecast_rating([], "overall", 7)
    assert result.predicted_delta is None
    assert result.n_points == 0


def test_forecast_result_is_frozen() -> None:
    snaps = _snaps_rising(10)
    result = forecast_rating(snaps, "overall", 7)
    with pytest.raises((AttributeError, TypeError)):
        result.predicted_delta = 999  # type: ignore[misc]
