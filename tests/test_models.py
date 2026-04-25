from datetime import UTC, datetime

from geostats.models import Account, GameMode, RatingSnapshot


def test_account_defaults():
    a = Account(id="abc", nick="Name", tracked=True, created_at=datetime.now(UTC))
    assert a.tracked is True
    assert a.last_polled_at is None
    assert a.last_error is None


def test_rating_snapshot_fields():
    snap = RatingSnapshot(
        account_id="abc",
        mode=GameMode.DUELS,
        rating=1500,
        games_played=10,
        captured_at=datetime.now(UTC),
    )
    assert snap.mode == GameMode.DUELS
    assert snap.rating == 1500  # noqa: PLR2004
