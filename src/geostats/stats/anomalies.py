from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.orm import Session

from geostats.models import AccountAnomaly

log = logging.getLogger(__name__)

FEATURES: tuple[str, ...] = (
    "peak_rating",
    "mean_rating",
    "rating_volatility",
    "rating_delta",
    "peak_win_streak",
    "mean_guessed_first_rate",
    "winrate",
    "mean_avg_guess_distance_km",
    "rating_efficiency",
    "streak_efficiency",
)
_FEATURE_DIM = len(FEATURES)
MIN_GAMES_PLAYED = 50
MIN_POPULATION = 50


@dataclass(frozen=True, slots=True)
class _Row:
    account_id: str
    vector: np.ndarray  # shape (_FEATURE_DIM,), no NaN


def _load_features(db: Session) -> list[_Row]:
    """Aggregate per-account features from rating_snapshots.

    Filters to tracked accounts whose latest snapshot has games_played >= MIN_GAMES_PLAYED.
    Drops accounts where any feature is null (e.g. rating fully missing).
    """
    sql = text("""
        WITH agg AS (
            SELECT
                rs.account_id,
                MAX(rs.rating) AS peak_rating,
                AVG(rs.rating)::float AS mean_rating,
                COALESCE(STDDEV_SAMP(rs.rating), 0.0)::float AS rating_volatility,
                MAX(rs.win_streak) AS peak_win_streak,
                AVG(rs.guessed_first_rate)::float AS mean_guessed_first_rate,
                AVG(rs.avg_guess_distance_km)::float AS mean_avg_guess_distance_km,
                MIN(rs.captured_at) AS first_at,
                MAX(rs.captured_at) AS last_at
            FROM rating_snapshots rs
            JOIN accounts a ON a.id = rs.account_id
            WHERE a.tracked = true AND rs.rating IS NOT NULL
            GROUP BY rs.account_id
        ),
        first_rating AS (
            SELECT DISTINCT ON (account_id) account_id, rating AS first_rating
            FROM rating_snapshots
            WHERE rating IS NOT NULL
            ORDER BY account_id, captured_at ASC
        ),
        last_rating AS (
            SELECT DISTINCT ON (account_id) account_id, rating AS last_rating
            FROM rating_snapshots
            WHERE rating IS NOT NULL
            ORDER BY account_id, captured_at DESC
        ),
        latest AS (
            SELECT DISTINCT ON (account_id)
                account_id, games_played, games_won
            FROM rating_snapshots
            WHERE games_played IS NOT NULL
            ORDER BY account_id, captured_at DESC
        )
        SELECT
            agg.account_id,
            agg.peak_rating,
            agg.mean_rating,
            agg.rating_volatility,
            agg.peak_win_streak,
            agg.mean_guessed_first_rate,
            agg.mean_avg_guess_distance_km,
            (lr.last_rating - fr.first_rating) AS rating_delta,
            l.games_played,
            l.games_won
        FROM agg
        JOIN first_rating fr ON fr.account_id = agg.account_id
        JOIN last_rating lr ON lr.account_id = agg.account_id
        JOIN latest l ON l.account_id = agg.account_id
        WHERE l.games_played >= :min_games
    """)
    rows: list[_Row] = []
    for r in db.execute(sql, {"min_games": MIN_GAMES_PLAYED}).fetchall():
        if (
            r.peak_rating is None
            or r.mean_rating is None
            or r.peak_win_streak is None
            or r.mean_guessed_first_rate is None
            or r.mean_avg_guess_distance_km is None
            or r.games_played is None
            or r.games_won is None
            or r.rating_delta is None
        ):
            continue
        winrate = r.games_won / r.games_played if r.games_played > 0 else 0.0
        log_games = math.log1p(r.games_played)
        vec = np.array(
            [
                float(r.peak_rating),
                float(r.mean_rating),
                float(r.rating_volatility),
                float(r.rating_delta),
                float(r.peak_win_streak),
                float(r.mean_guessed_first_rate),
                float(winrate),
                float(r.mean_avg_guess_distance_km),
                float(r.peak_rating) / log_games,
                float(r.peak_win_streak) / log_games,
            ],
            dtype=np.float64,
        )
        rows.append(_Row(account_id=r.account_id, vector=vec))
    return rows


CONFIDENCE_DISPLAY_THRESHOLD = 70  # consumed by the route layer
_RNG_SEED = 42
_N_ESTIMATORS = 200


def _percentile_rank(scores: np.ndarray) -> np.ndarray:
    """Map IsolationForest.score_samples output to anomaly percentile [0, 100].

    score_samples returns higher = more normal, so the lowest score is the most
    anomalous. We assign the most anomalous account 100% confidence and the most
    normal 0%.
    """
    n = scores.shape[0]
    if n == 0:
        return scores
    if n == 1:
        return np.array([0.0])
    order = np.argsort(scores)  # ascending: most anomalous first
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(n, dtype=np.float64)
    # rank 0 (lowest score) → 100% anomalous, rank n-1 → 0%.
    return 100.0 * (n - 1 - ranks) / (n - 1)


def _top_drivers(
    z_row: np.ndarray, k: int = 2
) -> list[tuple[str, float]]:
    order = np.argsort(-np.abs(z_row))[:k]
    return [(FEATURES[int(i)], float(z_row[int(i)])) for i in order]


def compute_anomalies(db: Session) -> int:
    rows = _load_features(db)
    if len(rows) < MIN_POPULATION:
        log.warning(
            "anomalies: population too small (%d < %d), skipping",
            len(rows), MIN_POPULATION,
        )
        return 0

    matrix = np.vstack([r.vector for r in rows])
    scaler = StandardScaler()
    scaled = scaler.fit_transform(matrix)

    clf = IsolationForest(
        n_estimators=_N_ESTIMATORS,
        contamination="auto",
        random_state=_RNG_SEED,
    )
    clf.fit(scaled)
    raw_scores = clf.score_samples(scaled)
    confidence = _percentile_rank(raw_scores)

    now = datetime.now(UTC)
    db.execute(text("DELETE FROM account_anomalies"))
    db.flush()

    batch: list[AccountAnomaly] = []
    for i, row in enumerate(rows):
        drivers = _top_drivers(scaled[i])
        d1, d2 = drivers[0], drivers[1] if len(drivers) > 1 else (None, None)
        batch.append(
            AccountAnomaly(
                account_id=row.account_id,
                score=float(raw_scores[i]),
                confidence_pct=int(round(float(np.clip(confidence[i], 0.0, 100.0)))),
                driver_1_feature=d1[0],
                driver_1_z=d1[1],
                driver_2_feature=d2[0] if d2[0] is not None else None,
                driver_2_z=d2[1] if d2[0] is not None else None,
                computed_at=now,
            )
        )
        if len(batch) >= 500:
            db.bulk_save_objects(batch)
            db.flush()
            batch.clear()
    if batch:
        db.bulk_save_objects(batch)
    db.commit()
    log.info("anomalies: wrote %d rows", len(rows))
    return len(rows)
