from datetime import UTC, datetime

from geostats.models import Account, RatingSnapshot


def test_account_defaults():
    a = Account(id="abc", nick="Name", tracked=True, created_at=datetime.now(UTC))
    assert a.tracked is True
    assert a.last_polled_at is None
    assert a.last_error is None
    assert a.is_pro is False
    assert a.level is None
    assert a.pin_url is None


def test_rating_snapshot_fields():
    snap = RatingSnapshot(
        account_id="abc",
        captured_at=datetime.now(UTC),
        rating=1500,
        division_name="Gold III",
        division_number=15,
        rating_moving=1550,
        rating_nomove=1400,
        rating_nmpz=1200,
        games_played=100,
        games_won=65,
    )
    assert snap.rating == 1500  # noqa: PLR2004
    assert snap.rating_moving == 1550  # noqa: PLR2004
    assert snap.position_overall is None
