from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy.orm import Session

from geostats.models import Account, PlayerMatch, RatingSnapshot
from geostats.stats.doppelganger import (
    WEIGHTS,
    _normalize_and_weight,
    _row_features,
    _similarity,
    compute_matches,
)


def test_row_features_handles_nones():
    f = _row_features(2500, 2400, 2450, 2300, 150.5, 0.5, 1000, 600)
    assert f.shape == (8,)
    assert f[0] == 2500.0
    assert pytest.approx(f[6], rel=1e-3) == 0.6
    assert pytest.approx(f[7], rel=1e-3) == np.log1p(1000)


def test_row_features_nan_for_missing():
    f = _row_features(None, None, None, None, None, None, None, None)
    assert np.all(np.isnan(f))


def test_normalize_and_weight_in_range():
    rows = np.array(
        [
            [1000, 900, 950, 800, 200, 0.3, 0.5, 5.0],
            [2000, 1900, 1950, 1800, 100, 0.5, 0.7, 7.0],
            [3000, 2900, 2950, 2800, 50, 0.7, 0.9, 9.0],
        ],
        dtype=np.float64,
    )
    out = _normalize_and_weight(rows)
    for col in range(out.shape[1]):
        c = out[:, col]
        assert c.min() >= 0.0 - 1e-9
        assert c.max() <= WEIGHTS[col] + 1e-9


def test_similarity_bounds():
    assert _similarity(0.0) == 100
    max_d = float(np.linalg.norm(WEIGHTS))
    assert _similarity(max_d) == 0
    assert 0 <= _similarity(max_d / 2) <= 100


def _seed_account(db: Session, *, id_: str, nick: str, country: str | None,
                  rating: int, dist: float, played: int, won: int) -> None:
    db.add(Account(id=id_, nick=nick, country_code=country, created_at=datetime.now(UTC)))
    db.add(RatingSnapshot(
        account_id=id_, captured_at=datetime.now(UTC) - timedelta(minutes=1),
        rating=rating, division_number=None, division_name=None,
        rating_moving=rating, rating_nomove=rating, rating_nmpz=rating,
        win_streak=None, guessed_first_rate=0.5,
        games_played=played, games_won=won, avg_guess_distance_km=dist,
        position_overall=None, position_moving=None, position_nomove=None,
        position_nmpz=None, position_country=None,
    ))
    db.flush()


def test_compute_matches_writes_rows(db: Session):
    _seed_account(db, id_="a", nick="A", country="US", rating=2500, dist=100, played=500, won=300)
    _seed_account(db, id_="b", nick="B", country="US", rating=2510, dist=102, played=510, won=305)
    _seed_account(db, id_="c", nick="C", country="DE", rating=1500, dist=300, played=200, won=80)
    _seed_account(db, id_="d", nick="D", country="DE", rating=1490, dist=295, played=210, won=85)
    db.commit()

    n = compute_matches(db)
    assert n == 4

    matches = {m.account_id: m for m in db.query(PlayerMatch).all()}
    assert len(matches) == 4

    # similar players (a/b, c/d) should match each other globally
    assert matches["a"].global_match_id == "b"
    assert matches["b"].global_match_id == "a"
    assert matches["c"].global_match_id == "d"
    assert matches["d"].global_match_id == "c"

    # country match same-country pair, similarity high
    assert matches["a"].country_match_id == "b"
    assert matches["a"].country_similarity is not None
    assert matches["a"].country_similarity > 90


def test_compute_matches_country_alone_is_null(db: Session):
    _seed_account(db, id_="a", nick="A", country="US", rating=2500, dist=100, played=500, won=300)
    _seed_account(db, id_="b", nick="B", country="US", rating=2510, dist=102, played=510, won=305)
    _seed_account(db, id_="c", nick="C", country="JP", rating=2000, dist=200, played=300, won=180)
    db.commit()

    compute_matches(db)
    m = db.query(PlayerMatch).filter_by(account_id="c").one()
    assert m.country_match_id is None
    assert m.country_similarity is None
    assert m.global_match_id in {"a", "b"}
