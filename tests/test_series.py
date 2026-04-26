from datetime import UTC, datetime, timedelta

from geostats.models import RatingSnapshot
from geostats.stats.series import get_series


def _now() -> datetime:
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=UTC)


def _snap(days_ago: float, rating: int | None = None, **kwargs) -> RatingSnapshot:
    return RatingSnapshot(
        account_id="acc1",
        captured_at=_now() - timedelta(days=days_ago),
        rating=rating,
        **kwargs,
    )


def test_get_series_filters_by_range():
    snaps = [_snap(60, rating=2000), _snap(20, rating=2100), _snap(5, rating=2200)]
    result = get_series(snaps, "overall", "30d")
    assert len(result) == 2
    assert result[0][1] == 2100
    assert result[1][1] == 2200


def test_get_series_omits_nulls():
    snaps = [_snap(5, rating=None), _snap(3, rating=2100)]
    result = get_series(snaps, "overall", "30d")
    assert len(result) == 1
    assert result[0][1] == 2100


def test_get_series_all_range_includes_old_snaps():
    snaps = [_snap(200, rating=2000), _snap(100, rating=2100)]
    result = get_series(snaps, "overall", "all")
    assert len(result) == 2


def test_get_series_7d_range():
    snaps = [_snap(10, rating=2000), _snap(3, rating=2100)]
    result = get_series(snaps, "overall", "7d")
    assert len(result) == 1
    assert result[0][1] == 2100


def test_get_series_90d_range():
    snaps = [_snap(100, rating=2000), _snap(50, rating=2100), _snap(5, rating=2200)]
    result = get_series(snaps, "overall", "90d")
    assert len(result) == 2


def test_get_series_mode_moving():
    snaps = [_snap(5, rating=2000, rating_moving=2500)]
    result = get_series(snaps, "moving", "30d")
    assert len(result) == 1
    assert result[0][1] == 2500


def test_get_series_mode_nomove():
    snaps = [_snap(5, rating_nomove=1900)]
    result = get_series(snaps, "nomove", "30d")
    assert result[0][1] == 1900


def test_get_series_mode_nmpz():
    snaps = [_snap(5, rating_nmpz=1800)]
    result = get_series(snaps, "nmpz", "30d")
    assert result[0][1] == 1800


def test_get_series_date_format():
    snaps = [_snap(5, rating=2100)]
    result = get_series(snaps, "overall", "30d")
    date_str = result[0][0]
    assert len(date_str) == 10
    assert date_str[4] == "-"
    assert date_str[7] == "-"


def test_get_series_empty_snaps():
    assert get_series([], "overall", "30d") == []
