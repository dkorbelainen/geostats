from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

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
    "log_games",
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
                float(log_games),
            ],
            dtype=np.float64,
        )
        rows.append(_Row(account_id=r.account_id, vector=vec))
    return rows
