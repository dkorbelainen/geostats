from datetime import UTC, datetime, timedelta

import pytest

from geostats.models import Account, RatingSnapshot
from geostats.ranker import compute_ranks

_OLD_CUTOFF = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def seeded_db(db):
    now = datetime.now(UTC)
    accounts = [
        Account(id="a1", nick="Alpha", country_code="us", tracked=True, created_at=now, last_polled_at=now),
        Account(id="a2", nick="Beta", country_code="us", tracked=True, created_at=now, last_polled_at=now),
        Account(id="a3", nick="Gamma", country_code="fi", tracked=True, created_at=now, last_polled_at=now),
    ]
    for a in accounts:
        db.add(a)
    db.flush()

    snapshots = [
        RatingSnapshot(
            account_id="a1", captured_at=now, rating=2000,
            rating_moving=1900, rating_nomove=1800, rating_nmpz=1700,
        ),
        RatingSnapshot(
            account_id="a2", captured_at=now, rating=1800,
            rating_moving=1700, rating_nomove=1600, rating_nmpz=1500,
        ),
        RatingSnapshot(
            account_id="a3", captured_at=now, rating=1900,
            rating_moving=1850, rating_nomove=1750, rating_nmpz=1650,
        ),
    ]
    for s in snapshots:
        db.add(s)
    db.flush()  # send INSERTs within the transaction; rollback in fixture teardown undoes all
    return db


def test_compute_ranks_overall(seeded_db):
    compute_ranks(seeded_db, cutoff=_OLD_CUTOFF)
    seeded_db.expire_all()

    a1_snap = seeded_db.query(RatingSnapshot).filter_by(account_id="a1").first()
    a2_snap = seeded_db.query(RatingSnapshot).filter_by(account_id="a2").first()
    a3_snap = seeded_db.query(RatingSnapshot).filter_by(account_id="a3").first()

    assert a1_snap.position_overall == 1
    assert a3_snap.position_overall == 2  # noqa: PLR2004
    assert a2_snap.position_overall == 3  # noqa: PLR2004


def test_compute_ranks_per_mode(seeded_db):
    compute_ranks(seeded_db, cutoff=_OLD_CUTOFF)
    seeded_db.expire_all()

    a1 = seeded_db.query(RatingSnapshot).filter_by(account_id="a1").first()
    assert a1.position_moving == 1
    assert a1.position_nomove == 1
    assert a1.position_nmpz == 1


def test_compute_ranks_country(seeded_db):
    compute_ranks(seeded_db, cutoff=_OLD_CUTOFF)
    seeded_db.expire_all()

    # a1 and a2 are both "us" — a1 has higher rating
    a1 = seeded_db.query(RatingSnapshot).filter_by(account_id="a1").first()
    a2 = seeded_db.query(RatingSnapshot).filter_by(account_id="a2").first()
    a3 = seeded_db.query(RatingSnapshot).filter_by(account_id="a3").first()

    assert a1.position_country == 1
    assert a2.position_country == 2  # noqa: PLR2004
    assert a3.position_country == 1  # only "fi" player


def test_compute_ranks_excludes_pre_cutoff_accounts(db):
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=1)
    accounts = [
        Account(id="new1", nick="New1", country_code="us", tracked=True, created_at=now, last_polled_at=now),
        Account(id="new2", nick="New2", country_code="us", tracked=True, created_at=now, last_polled_at=now),
        Account(id="stale", nick="Stale", country_code="us", tracked=True, created_at=now, last_polled_at=cutoff - timedelta(days=10)),
    ]
    for a in accounts:
        db.add(a)
    db.flush()

    db.add(RatingSnapshot(account_id="new1", captured_at=now, rating=2000))
    db.add(RatingSnapshot(account_id="new2", captured_at=now, rating=1800))
    db.add(RatingSnapshot(account_id="stale", captured_at=cutoff - timedelta(days=10), rating=5000))
    db.flush()

    compute_ranks(db, cutoff=cutoff)
    db.expire_all()

    new1 = db.query(RatingSnapshot).filter_by(account_id="new1").first()
    new2 = db.query(RatingSnapshot).filter_by(account_id="new2").first()
    stale = db.query(RatingSnapshot).filter_by(account_id="stale").first()

    assert new1.position_overall == 1
    assert new2.position_overall == 2  # noqa: PLR2004
    assert stale.position_overall is None
