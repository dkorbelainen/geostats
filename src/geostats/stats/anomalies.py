"""Hybrid anomaly detection.

Pipeline
--------
1. Aggregate per-account features from rating_snapshots + accounts.
2. Bucket players by peak_rating tier (peer baseline).
3. Within each bucket fit IsolationForest, robust-standardize the raw
   anomaly score via median/MAD, squash to a probability with a sigmoid.
   Buckets smaller than MIN_BUCKET fall back to a global model.
4. Compute a rule-based suspicion prior from domain heuristics (low games
   + high rating, low level + high rating, suspiciously close average
   guess distance, extreme streaks, very high "guessed first" rate).
   Each rule is a smooth sigmoid in [0, 1]; the rules combine via
   noisy-OR so multiple weak signals reinforce each other.
5. Final confidence = noisy-OR(if_prob, rule_score) → percentile in [0, 100].
6. Drivers: the two features with the largest |z| in the per-bucket scaled
   vector, used to label the anomaly card.
"""
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
    "log_games_played",
    "account_level",
    "rating_per_level",
)
_FEATURE_DIM = len(FEATURES)

MIN_GAMES_PLAYED = 50
MIN_POPULATION = 50
MIN_BUCKET = 25  # below this, fall back to global IF model

# peak_rating bucket edges (right-open). 6 buckets total.
_BUCKET_EDGES: tuple[float, ...] = (1100.0, 1300.0, 1500.0, 1700.0, 1900.0)

# Per-bucket multiplier on the final anomaly confidence.
# Low-rating tiers are noisy: rule_prior fires on "few games + high rating"
# even at 1100, and the IF tail is thin. Scale down so flat display threshold
# of 85 effectively hides bucket 0 and trims bucket 1.
_BUCKET_CONFIDENCE_WEIGHT: tuple[float, ...] = (0.0, 0.82, 0.95, 1.0, 1.0, 1.0)

CONFIDENCE_DISPLAY_THRESHOLD = 85
_RNG_SEED = 42
_N_ESTIMATORS = 200


@dataclass(frozen=True, slots=True)
class _Row:
    account_id: str
    vector: np.ndarray  # shape (_FEATURE_DIM,), no NaN
    raw: dict[str, float]  # raw values for rule-based scoring


def _load_features(db: Session, cutoff: datetime) -> list[_Row]:
    """Aggregate per-account features.

    Filters to tracked accounts whose latest snapshot has games_played >=
    MIN_GAMES_PLAYED, restricted to snapshots captured on/after cutoff.
    Drops accounts where any required feature is null. Missing
    account_level is median-imputed across the surviving population.
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
                AVG(rs.avg_guess_distance_km)::float AS mean_avg_guess_distance_km
            FROM rating_snapshots rs
            JOIN accounts a ON a.id = rs.account_id
            WHERE a.tracked = true AND rs.rating IS NOT NULL AND rs.captured_at >= :cutoff
            GROUP BY rs.account_id
        ),
        first_rating AS (
            SELECT DISTINCT ON (account_id) account_id, rating AS first_rating
            FROM rating_snapshots
            WHERE rating IS NOT NULL AND captured_at >= :cutoff
            ORDER BY account_id, captured_at ASC
        ),
        last_rating AS (
            SELECT DISTINCT ON (account_id) account_id, rating AS last_rating
            FROM rating_snapshots
            WHERE rating IS NOT NULL AND captured_at >= :cutoff
            ORDER BY account_id, captured_at DESC
        ),
        latest AS (
            SELECT DISTINCT ON (account_id)
                account_id, games_played, games_won
            FROM rating_snapshots
            WHERE games_played IS NOT NULL AND captured_at >= :cutoff
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
            l.games_won,
            a.level AS account_level
        FROM agg
        JOIN first_rating fr ON fr.account_id = agg.account_id
        JOIN last_rating lr ON lr.account_id = agg.account_id
        JOIN latest l ON l.account_id = agg.account_id
        JOIN accounts a ON a.id = agg.account_id
        WHERE l.games_played >= :min_games
    """)

    pending: list[tuple[str, dict[str, float], int | None]] = []
    levels_seen: list[float] = []
    for r in db.execute(sql, {"min_games": MIN_GAMES_PLAYED, "cutoff": cutoff}).fetchall():
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
        raw: dict[str, float] = {
            "peak_rating": float(r.peak_rating),
            "mean_rating": float(r.mean_rating),
            "rating_volatility": float(r.rating_volatility),
            "rating_delta": float(r.rating_delta),
            "peak_win_streak": float(r.peak_win_streak),
            "mean_guessed_first_rate": float(r.mean_guessed_first_rate),
            "winrate": float(winrate),
            "mean_avg_guess_distance_km": float(r.mean_avg_guess_distance_km),
            "rating_efficiency": float(r.peak_rating) / log_games,
            "streak_efficiency": float(r.peak_win_streak) / log_games,
            "log_games_played": float(log_games),
            "games_played": float(r.games_played),
        }
        pending.append((r.account_id, raw, r.account_level))
        if r.account_level is not None:
            levels_seen.append(float(r.account_level))

    if not pending:
        return []

    median_level = float(np.median(levels_seen)) if levels_seen else 50.0

    rows: list[_Row] = []
    for account_id, raw, lvl in pending:
        known = lvl is not None
        level_val = float(lvl) if known else median_level
        raw["account_level"] = level_val
        raw["rating_per_level"] = raw["peak_rating"] / max(level_val, 1.0)
        raw["_level_known"] = 1.0 if known else 0.0
        vec = np.array([raw[name] for name in FEATURES], dtype=np.float64)
        rows.append(_Row(account_id=account_id, vector=vec, raw=raw))
    return rows


def _bucket_index(peak_rating: float) -> int:
    for i, edge in enumerate(_BUCKET_EDGES):
        if peak_rating < edge:
            return i
    return len(_BUCKET_EDGES)


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


_RULE_PRIOR_CAP = 0.85  # leave headroom so IF can still differentiate
_IF_PROB_CAP = 0.90  # cap IF alone — only IF + rules together can hit ~99%


def _rule_score(raw: dict[str, float]) -> float:
    """Soft domain-rule prior in [0, 1]. Combines signals via noisy-OR.

    Skill markers (close distance, fast guesses, long streaks) only fire in
    combination with low game count — pros legitimately have those traits.
    The level-vs-rating rule is skipped when the account level is unknown.
    Final value is capped at _RULE_PRIOR_CAP to leave room for the IF model
    to differentiate accounts whose rule signals all saturate.
    """
    rating = raw["peak_rating"]
    games = raw["games_played"]
    level = raw["account_level"]
    streak = raw["peak_win_streak"]
    distance = raw["mean_avg_guess_distance_km"]
    gfr = raw["mean_guessed_first_rate"]
    level_known = raw["_level_known"] > 0.0

    high_rating = _sigmoid((rating - 1500.0) / 100.0)
    low_games = _sigmoid(-(games - 1000.0) / 300.0)

    signals: list[float] = [
        # few games + high rating
        low_games * high_rating,
        # close average distance + few games
        _sigmoid(-(distance - 700.0) / 150.0) * low_games,
        # extreme streak + few games
        _sigmoid((streak - 12.0) / 4.0) * low_games,
        # very high "guessed first" rate + few games
        _sigmoid((gfr - 0.65) / 0.08) * low_games,
    ]
    if level_known:
        signals.append(_sigmoid(-(level - 70.0) / 15.0) * high_rating)

    p_clean = 1.0
    for s in signals:
        p_clean *= 1.0 - s
    return min(1.0 - p_clean, _RULE_PRIOR_CAP)


def _if_probability(scaled: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fit IsolationForest on scaled rows, return (raw_score, prob).

    raw_score is the sklearn score_samples output (higher = more normal).
    prob is the calibrated anomaly probability in [0, 1] derived from the
    robust z-score (median/MAD) of the negated raw score.
    """
    if scaled.shape[0] == 0:
        return np.array([]), np.array([])
    if scaled.shape[0] == 1:
        return np.array([0.0]), np.array([0.0])

    clf = IsolationForest(
        n_estimators=_N_ESTIMATORS,
        contamination="auto",
        random_state=_RNG_SEED,
    )
    clf.fit(scaled)
    raw = clf.score_samples(scaled)
    anomaly = -raw  # higher = more anomalous
    eps = 1e-9
    med = float(np.median(anomaly))
    mad = float(np.median(np.abs(anomaly - med)))
    scale = 1.4826 * mad if mad > eps else float(np.std(anomaly) + eps)
    z = (anomaly - med) / scale
    # sigmoid centred at z=1.5 — roughly 1.5 robust SD above median = 50%.
    prob = 1.0 / (1.0 + np.exp(-(z - 1.5) / 0.7))
    return raw, prob


def _top_drivers(z_row: np.ndarray, k: int = 2) -> list[tuple[str, float]]:
    order = np.argsort(-np.abs(z_row))[:k]
    return [(FEATURES[int(i)], float(z_row[int(i)])) for i in order]


def compute_anomalies(db: Session, cutoff: datetime) -> int:
    rows = _load_features(db, cutoff)
    if len(rows) < MIN_POPULATION:
        log.warning(
            "anomalies: population too small (%d < %d), skipping",
            len(rows), MIN_POPULATION,
        )
        return 0

    n = len(rows)
    matrix = np.vstack([r.vector for r in rows])

    # Global model — used as fallback for tiny buckets and as a sanity floor.
    global_scaler = StandardScaler()
    global_scaled = global_scaler.fit_transform(matrix)
    global_raw, global_prob = _if_probability(global_scaled)

    if_prob = np.zeros(n, dtype=np.float64)
    if_raw = np.zeros(n, dtype=np.float64)
    scaled_per_row = np.zeros_like(matrix)

    # Bucket assignment.
    bucket_ids = np.array(
        [_bucket_index(r.raw["peak_rating"]) for r in rows], dtype=np.int64
    )

    for b in np.unique(bucket_ids):
        idx = np.where(bucket_ids == b)[0]
        if idx.size < MIN_BUCKET:
            # fall back to global score for this bucket
            if_prob[idx] = global_prob[idx]
            if_raw[idx] = global_raw[idx]
            scaled_per_row[idx] = global_scaled[idx]
            continue
        sub = matrix[idx]
        scaler = StandardScaler()
        sub_scaled = scaler.fit_transform(sub)
        sub_raw, sub_prob = _if_probability(sub_scaled)
        if_prob[idx] = sub_prob
        if_raw[idx] = sub_raw
        scaled_per_row[idx] = sub_scaled

    rule_prob = np.array([_rule_score(r.raw) for r in rows], dtype=np.float64)
    if_prob_capped = np.clip(if_prob, 0.0, _IF_PROB_CAP)

    # Noisy-OR fusion: either signal alone can flag, both reinforce.
    combined = 1.0 - (1.0 - if_prob_capped) * (1.0 - rule_prob)
    bucket_weights = np.array(
        [_BUCKET_CONFIDENCE_WEIGHT[int(b)] for b in bucket_ids],
        dtype=np.float64,
    )
    confidence = np.clip(combined * bucket_weights * 100.0, 0.0, 100.0)

    now = datetime.now(UTC)
    db.execute(text("DELETE FROM account_anomalies"))
    db.flush()

    batch: list[AccountAnomaly] = []
    for i, row in enumerate(rows):
        drivers = _top_drivers(scaled_per_row[i])
        d1 = drivers[0]
        d2 = drivers[1] if len(drivers) > 1 else (None, None)
        batch.append(
            AccountAnomaly(
                account_id=row.account_id,
                score=float(if_raw[i]),
                confidence_pct=int(round(float(confidence[i]))),
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
    log.info("anomalies: wrote %d rows", n)
    return n
