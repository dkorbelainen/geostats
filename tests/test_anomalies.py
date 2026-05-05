from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
from click.testing import CliRunner
from sqlalchemy.orm import Session

from geostats.cli import cli
from geostats.models import Account, AccountAnomaly, RatingSnapshot
from geostats.stats.anomalies import (
    CONFIDENCE_DISPLAY_THRESHOLD,
    FEATURES,
    MIN_POPULATION,
    _load_features,
    compute_anomalies,
)


def test_account_anomaly_persists(db: Session) -> None:
    db.add(Account(id="a1", nick="A1", created_at=datetime.now(UTC)))
    db.flush()
    db.add(
        AccountAnomaly(
            account_id="a1",
            score=-0.12,
            confidence_pct=82,
            driver_1_feature="peak_win_streak",
            driver_1_z=3.1,
            driver_2_feature="mean_avg_guess_distance_km",
            driver_2_z=-2.4,
            computed_at=datetime.now(UTC),
        )
    )
    db.commit()

    row = db.get(AccountAnomaly, "a1")
    assert row is not None
    assert row.confidence_pct == 82
    assert row.driver_1_feature == "peak_win_streak"
    assert row.driver_2_z == -2.4


def _seed_snapshot(
    db: Session,
    account_id: str,
    captured_at: datetime,
    *,
    rating: int | None,
    win_streak: int | None = None,
    guessed_first_rate: float | None = None,
    games_played: int | None = None,
    games_won: int | None = None,
    avg_guess_distance_km: float | None = None,
) -> None:
    db.add(
        RatingSnapshot(
            account_id=account_id,
            captured_at=captured_at,
            rating=rating,
            division_number=None,
            division_name=None,
            rating_moving=None,
            rating_nomove=None,
            rating_nmpz=None,
            win_streak=win_streak,
            guessed_first_rate=guessed_first_rate,
            games_played=games_played,
            games_won=games_won,
            avg_guess_distance_km=avg_guess_distance_km,
            position_overall=None,
            position_moving=None,
            position_nomove=None,
            position_nmpz=None,
            position_country=None,
        )
    )


def test_load_features_filters_low_volume(db: Session) -> None:
    now = datetime.now(UTC)
    db.add(Account(id="hi", nick="hi", created_at=now))
    db.add(Account(id="lo", nick="lo", created_at=now))
    db.flush()

    _seed_snapshot(
        db, "hi", now, rating=2000, win_streak=4,
        guessed_first_rate=0.4, games_played=120, games_won=70,
        avg_guess_distance_km=180.0,
    )
    _seed_snapshot(
        db, "lo", now, rating=1500, win_streak=2,
        guessed_first_rate=0.3, games_played=10, games_won=5,
        avg_guess_distance_km=600.0,
    )
    db.commit()

    rows = _load_features(db)
    assert [r.account_id for r in rows] == ["hi"]
    assert rows[0].vector.shape == (len(FEATURES),)


def test_load_features_aggregates_history(db: Session) -> None:
    now = datetime.now(UTC)
    db.add(Account(id="x", nick="x", created_at=now))
    db.flush()

    _seed_snapshot(
        db, "x", now - timedelta(days=10), rating=1800, win_streak=3,
        guessed_first_rate=0.5, games_played=100, games_won=55,
        avg_guess_distance_km=200.0,
    )
    _seed_snapshot(
        db, "x", now, rating=2000, win_streak=7,
        guessed_first_rate=0.6, games_played=200, games_won=120,
        avg_guess_distance_km=150.0,
    )
    db.commit()

    rows = _load_features(db)
    assert len(rows) == 1
    feats = dict(zip(FEATURES, rows[0].vector, strict=True))
    assert feats["peak_rating"] == 2000.0
    assert feats["mean_rating"] == 1900.0
    assert feats["rating_delta"] == 200.0
    assert feats["peak_win_streak"] == 7.0
    assert feats["winrate"] == 120 / 200
    assert "log_games" not in feats
    log_g = math.log1p(200)
    assert abs(feats["rating_efficiency"] - 2000.0 / log_g) < 1e-6
    assert abs(feats["streak_efficiency"] - 7.0 / log_g) < 1e-6
    assert abs(feats["rating_volatility"] - np.std([1800.0, 2000.0], ddof=1)) < 1e-6


def _seed_typical(db: Session, account_id: str, *, rating: int, streak: int,
                  gfr: float, played: int, won: int, dist_km: float) -> None:
    now = datetime.now(UTC)
    db.add(Account(id=account_id, nick=account_id, created_at=now))
    db.flush()
    _seed_snapshot(
        db, account_id, now, rating=rating, win_streak=streak,
        guessed_first_rate=gfr, games_played=played, games_won=won,
        avg_guess_distance_km=dist_km,
    )


def test_compute_anomalies_skips_when_population_too_small(db: Session) -> None:
    for i in range(5):
        _seed_typical(
            db, f"u{i}", rating=1500 + i, streak=3, gfr=0.4,
            played=200, won=110, dist_km=300.0,
        )
    db.commit()

    n = compute_anomalies(db)
    assert n == 0
    assert db.query(AccountAnomaly).count() == 0


def test_compute_anomalies_writes_rows_and_finds_outlier(db: Session) -> None:
    for i in range(MIN_POPULATION):
        _seed_typical(
            db, f"u{i:03d}", rating=1500 + (i % 5) * 10, streak=3 + i % 2,
            gfr=0.40 + (i % 3) * 0.005, played=200 + i, won=110 + (i % 3),
            dist_km=300.0 + (i % 4),
        )
    _seed_typical(
        db, "outlier", rating=2700, streak=20, gfr=0.92,
        played=400, won=380, dist_km=40.0,
    )
    db.commit()

    n = compute_anomalies(db)
    assert n == MIN_POPULATION + 1

    rows = {r.account_id: r for r in db.query(AccountAnomaly).all()}
    assert len(rows) == n

    outlier = rows["outlier"]
    assert 0 <= outlier.confidence_pct <= 100
    assert outlier.confidence_pct >= CONFIDENCE_DISPLAY_THRESHOLD
    assert outlier.driver_1_feature in FEATURES
    typical_pcts = [rows[f"u{i:03d}"].confidence_pct for i in range(MIN_POPULATION)]
    assert outlier.confidence_pct > max(typical_pcts)


def test_suspicious_low_games_high_rating_scores_above_legit(db: Session) -> None:
    """Cheater pattern: high rating + high streak in few games should rank above
    a legitimate top player with many games and equivalent rating."""
    for i in range(MIN_POPULATION):
        _seed_typical(
            db, f"u{i:03d}", rating=1400 + (i % 5) * 10, streak=2 + i % 3,
            gfr=0.35 + (i % 4) * 0.01, played=300 + i * 2, won=160 + i,
            dist_km=320.0 + (i % 5),
        )
    # legitimate top player: many games, high rating, moderate streak
    _seed_typical(
        db, "legit_top", rating=2400, streak=8,
        gfr=0.70, played=3000, won=2100, dist_km=90.0,
    )
    # suspicious: same high rating, tiny game count, extreme streak
    _seed_typical(
        db, "suspicious", rating=2300, streak=26,
        gfr=0.90, played=240, won=230, dist_km=180.0,
    )
    db.commit()

    compute_anomalies(db)

    rows = {r.account_id: r for r in db.query(AccountAnomaly).all()}
    assert rows["suspicious"].confidence_pct > rows["legit_top"].confidence_pct


def test_compute_anomalies_replaces_previous_results(db: Session) -> None:
    for i in range(MIN_POPULATION + 1):
        _seed_typical(
            db, f"u{i:03d}", rating=1500 + i, streak=3, gfr=0.4,
            played=200 + i, won=110, dist_km=300.0,
        )
    db.commit()

    compute_anomalies(db)
    first_ts = db.query(AccountAnomaly.computed_at).first()
    assert first_ts is not None

    n2 = compute_anomalies(db)
    assert n2 == MIN_POPULATION + 1
    assert db.query(AccountAnomaly).count() == n2


def test_compute_anomalies_cli_smoke(monkeypatch, db: Session) -> None:
    from contextlib import contextmanager

    @contextmanager
    def fake_scope():
        yield db

    monkeypatch.setattr("geostats.db.session_factory", lambda: None)
    monkeypatch.setattr("geostats.db.session_scope", fake_scope)

    for i in range(MIN_POPULATION + 1):
        _seed_typical(
            db, f"u{i:03d}", rating=1500 + i, streak=3, gfr=0.4,
            played=200 + i, won=110, dist_km=300.0,
        )
    db.commit()

    runner = CliRunner()
    result = runner.invoke(cli, ["compute-anomalies"])
    assert result.exit_code == 0, result.output
    assert "anomalies" in result.output.lower()
    assert db.query(AccountAnomaly).count() == MIN_POPULATION + 1
