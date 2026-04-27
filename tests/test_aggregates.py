from datetime import datetime, timedelta, timezone

from geostats.models import Account, RatingSnapshot
from geostats.stats.aggregates import (
    RATING_FIELDS,
    average_rate_per_week,
    current_rating,
    delta_over_period,
    record,
    summarize_profile,
)

_RATING_2000 = 2000
_RATING_2100 = 2100
_RATING_2200 = 2200
_RATING_2300 = 2300
_RATING_2500 = 2500
_RATING_DELTA_100 = 100
_RATING_DELTA_NEG_100 = -100
_AVG_TOLERANCE = 0.1


def _now() -> datetime:
    return datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)  # noqa: UP017


def _snap(days_ago: float, rating: int | None = None, **kwargs) -> RatingSnapshot:
    return RatingSnapshot(
        account_id="acc1",
        captured_at=_now() - timedelta(days=days_ago),
        rating=rating,
        **kwargs,
    )


def _account() -> Account:
    return Account(id="acc1", nick="player1", created_at=_now())


# current_rating

def test_current_rating_returns_latest_nonnull():
    snaps = [_snap(3, rating=_RATING_2000), _snap(2, rating=None), _snap(1, rating=_RATING_2100)]
    assert current_rating(snaps, "overall") == _RATING_2100


def test_current_rating_skips_trailing_null():
    snaps = [_snap(2, rating=_RATING_2000), _snap(1, rating=None)]
    assert current_rating(snaps, "overall") == _RATING_2000


def test_current_rating_all_null_returns_none():
    assert current_rating([_snap(1, rating=None)], "overall") is None


def test_current_rating_empty_returns_none():
    assert current_rating([], "overall") is None


def test_current_rating_moving_field():
    snaps = [_snap(1, rating_moving=_RATING_2500)]
    assert current_rating(snaps, "moving") == _RATING_2500


# delta_over_period

def test_delta_over_period_positive():
    now = _now()
    snaps = [_snap(10, rating=_RATING_2000), _snap(1, rating=_RATING_2100)]
    result = delta_over_period(snaps, "overall", now=now, window=timedelta(days=7))
    assert result == _RATING_DELTA_100


def test_delta_over_period_negative():
    now = _now()
    snaps = [_snap(10, rating=_RATING_2200), _snap(1, rating=_RATING_2100)]
    result = delta_over_period(snaps, "overall", now=now, window=timedelta(days=7))
    assert result == _RATING_DELTA_NEG_100


def test_delta_over_period_no_snap_before_cutoff_returns_none():
    now = _now()
    snaps = [_snap(3, rating=2100)]
    result = delta_over_period(snaps, "overall", now=now, window=timedelta(days=7))
    assert result is None


def test_delta_over_period_no_latest_returns_none():
    now = _now()
    snaps = [_snap(10, rating=2000), _snap(1, rating=None)]
    result = delta_over_period(snaps, "overall", now=now, window=timedelta(days=7))
    assert result is None


# record

def test_record_returns_max():
    snaps = [
        _snap(3, rating=_RATING_2200),
        _snap(2, rating=_RATING_2500),
        _snap(1, rating=_RATING_2300),
    ]
    r = record(snaps, "overall")
    assert r is not None
    assert r.value == _RATING_2500


def test_record_skips_nulls():
    snaps = [_snap(2, rating=None), _snap(1, rating=_RATING_2100)]
    r = record(snaps, "overall")
    assert r is not None
    assert r.value == _RATING_2100


def test_record_empty_returns_none():
    assert record([], "overall") is None


def test_record_all_null_returns_none():
    assert record([_snap(1, rating=None)], "overall") is None


def test_record_captured_at():
    t = _now() - timedelta(days=2)
    snaps = [
        RatingSnapshot(account_id="acc1", captured_at=t, rating=_RATING_2500),
        _snap(1, rating=_RATING_2300),
    ]
    r = record(snaps, "overall")
    assert r is not None
    assert r.captured_at == t


# average_rate_per_week

def test_average_rate_per_week_rising():
    now = _now()
    snaps = [_snap(28, rating=_RATING_2000), _snap(1, rating=2140)]
    result = average_rate_per_week(snaps, "overall", now=now, window=timedelta(days=30))
    assert result is not None
    assert abs(result - 140 / 30 * 7) < _AVG_TOLERANCE


def test_average_rate_per_week_one_snap_returns_none():
    now = _now()
    snaps = [_snap(5, rating=2000)]
    assert average_rate_per_week(snaps, "overall", now=now, window=timedelta(days=30)) is None


def test_average_rate_per_week_no_snaps_returns_none():
    now = _now()
    assert average_rate_per_week([], "overall", now=now, window=timedelta(days=30)) is None


# RATING_FIELDS

def test_rating_fields_contains_all_modes():
    assert set(RATING_FIELDS) == {"overall", "moving", "nomove", "nmpz"}


# summarize_profile

def test_summarize_profile_populates_all_keys():
    acc = _account()
    snaps = [_snap(10, rating=_RATING_2000), _snap(1, rating=_RATING_2100)]
    summary = summarize_profile(acc, snaps)
    assert summary.account is acc
    assert set(summary.current.keys()) == set(RATING_FIELDS)
    assert set(summary.delta_7d.keys()) == set(RATING_FIELDS)
    assert set(summary.delta_30d.keys()) == set(RATING_FIELDS)
    assert set(summary.record.keys()) == set(RATING_FIELDS)
    assert set(summary.avg_per_week_30d.keys()) == set(RATING_FIELDS)
    assert set(summary.percentile.keys()) == set(RATING_FIELDS)


def test_summarize_profile_has_percentile_keys() -> None:
    acc = _account()
    snaps = [_snap(10, rating=_RATING_2000), _snap(1, rating=_RATING_2100)]
    summary = summarize_profile(acc, snaps)
    assert set(summary.percentile.keys()) == set(RATING_FIELDS)


def test_summarize_profile_percentile_calculated() -> None:
    acc = _account()
    snap = _snap(1, rating=_RATING_2100)
    snap.position_overall = 10
    snaps = [snap]
    summary = summarize_profile(acc, snaps, total_tracked=100)
    assert summary.percentile["overall"] == 90.0


def test_summarize_profile_percentile_none_when_no_position() -> None:
    acc = _account()
    snaps = [_snap(1, rating=_RATING_2100)]
    summary = summarize_profile(acc, snaps, total_tracked=100)
    assert summary.percentile["overall"] is None


def test_summarize_profile_percentile_none_when_total_zero() -> None:
    acc = _account()
    snap = _snap(1, rating=_RATING_2100)
    snap.position_overall = 5
    snaps = [snap]
    summary = summarize_profile(acc, snaps, total_tracked=0)
    assert summary.percentile["overall"] is None


def test_summarize_profile_default_total_tracked_is_zero() -> None:
    acc = _account()
    snap = _snap(1, rating=_RATING_2100)
    snap.position_overall = 5
    snaps = [snap]
    summary = summarize_profile(acc, snaps)
    assert summary.percentile["overall"] is None
