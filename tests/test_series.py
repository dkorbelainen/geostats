from datetime import UTC, datetime, timedelta

from geostats.models import RatingSnapshot
from geostats.stats.series import get_series

_RATING_2000 = 2000
_RATING_2100 = 2100
_RATING_2200 = 2200
_RATING_2500 = 2500
_RATING_1900 = 1900
_RATING_1800 = 1800
_DATE_STR_LEN = 10
_DATE_HYPHEN_IDX_1 = 4
_DATE_HYPHEN_IDX_2 = 7
_RESULT_COUNT_2 = 2


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
    snaps = [
        _snap(60, rating=_RATING_2000),
        _snap(20, rating=_RATING_2100),
        _snap(5, rating=_RATING_2200),
    ]
    result = get_series(snaps, "overall", "30d", now=_now())
    assert len(result) == _RESULT_COUNT_2
    assert result[0][1] == _RATING_2100
    assert result[1][1] == _RATING_2200


def test_get_series_omits_nulls():
    snaps = [_snap(5, rating=None), _snap(3, rating=_RATING_2100)]
    result = get_series(snaps, "overall", "30d", now=_now())
    assert len(result) == 1
    assert result[0][1] == _RATING_2100


def test_get_series_all_range_includes_old_snaps():
    snaps = [_snap(200, rating=_RATING_2000), _snap(100, rating=_RATING_2100)]
    result = get_series(snaps, "overall", "all")
    assert len(result) == _RESULT_COUNT_2


def test_get_series_7d_range():
    snaps = [_snap(10, rating=_RATING_2000), _snap(3, rating=_RATING_2100)]
    result = get_series(snaps, "overall", "7d", now=_now())
    assert len(result) == 1
    assert result[0][1] == _RATING_2100


def test_get_series_90d_range():
    snaps = [
        _snap(100, rating=_RATING_2000),
        _snap(50, rating=_RATING_2100),
        _snap(5, rating=_RATING_2200),
    ]
    result = get_series(snaps, "overall", "90d", now=_now())
    assert len(result) == _RESULT_COUNT_2


def test_get_series_mode_moving():
    snaps = [_snap(5, rating=_RATING_2000, rating_moving=_RATING_2500)]
    result = get_series(snaps, "moving", "30d", now=_now())
    assert len(result) == 1
    assert result[0][1] == _RATING_2500


def test_get_series_mode_nomove():
    snaps = [_snap(5, rating_nomove=_RATING_1900)]
    result = get_series(snaps, "nomove", "30d", now=_now())
    assert result[0][1] == _RATING_1900


def test_get_series_mode_nmpz():
    snaps = [_snap(5, rating_nmpz=_RATING_1800)]
    result = get_series(snaps, "nmpz", "30d", now=_now())
    assert result[0][1] == _RATING_1800


def test_get_series_date_format():
    snaps = [_snap(5, rating=_RATING_2100)]
    result = get_series(snaps, "overall", "30d", now=_now())
    date_str = result[0][0]
    assert len(date_str) == _DATE_STR_LEN
    assert date_str[_DATE_HYPHEN_IDX_1] == "-"
    assert date_str[_DATE_HYPHEN_IDX_2] == "-"


def test_get_series_empty_snaps():
    assert get_series([], "overall", "30d") == []
