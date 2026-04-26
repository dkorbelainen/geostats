from datetime import UTC, datetime

import pytest

from geostats.models import Account, RatingSnapshot
from geostats.ranker import compute_ranks


@pytest.fixture
def seeded_db(db):
    now = datetime.now(UTC)
    accounts = [
        Account(id="a1", nick="Alpha", country_code="us", tracked=True, created_at=now),
        Account(id="a2", nick="Beta", country_code="us", tracked=True, created_at=now),
        Account(id="a3", nick="Gamma", country_code="fi", tracked=True, created_at=now),
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
    compute_ranks(seeded_db)
    seeded_db.expire_all()

    a1_snap = seeded_db.query(RatingSnapshot).filter_by(account_id="a1").first()
    a2_snap = seeded_db.query(RatingSnapshot).filter_by(account_id="a2").first()
    a3_snap = seeded_db.query(RatingSnapshot).filter_by(account_id="a3").first()

    assert a1_snap.position_overall == 1
    assert a3_snap.position_overall == 2  # noqa: PLR2004
    assert a2_snap.position_overall == 3  # noqa: PLR2004


def test_compute_ranks_per_mode(seeded_db):
    compute_ranks(seeded_db)
    seeded_db.expire_all()

    a1 = seeded_db.query(RatingSnapshot).filter_by(account_id="a1").first()
    assert a1.position_moving == 1
    assert a1.position_nomove == 1
    assert a1.position_nmpz == 1


def test_compute_ranks_country(seeded_db):
    compute_ranks(seeded_db)
    seeded_db.expire_all()

    # a1 and a2 are both "us" — a1 has higher rating
    a1 = seeded_db.query(RatingSnapshot).filter_by(account_id="a1").first()
    a2 = seeded_db.query(RatingSnapshot).filter_by(account_id="a2").first()
    a3 = seeded_db.query(RatingSnapshot).filter_by(account_id="a3").first()

    assert a1.position_country == 1
    assert a2.position_country == 2  # noqa: PLR2004
    assert a3.position_country == 1  # only "fi" player
