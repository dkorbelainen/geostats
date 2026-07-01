from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sklearn.neighbors import NearestNeighbors
from sqlalchemy import text
from sqlalchemy.orm import Session

from geostats.models import PlayerMatch

log = logging.getLogger(__name__)

FEATURES = (
    "rating",
    "rating_moving",
    "rating_nomove",
    "rating_nmpz",
    "avg_guess_distance_km",
    "guessed_first_rate",
    "win_rate",
    "log_games",
)
WEIGHTS = np.array([0.40, 0.10, 0.10, 0.10, 0.10, 0.10, 0.05, 0.05], dtype=np.float64)
assert math.isclose(WEIGHTS.sum(), 1.0)

_FEATURE_DIM = len(FEATURES)


@dataclass(frozen=True, slots=True)
class _Row:
    account_id: str
    country_code: str | None
    features: np.ndarray  # raw, length _FEATURE_DIM, NaN allowed


def _row_features(rating: int | None, moving: int | None, nomove: int | None,
                  nmpz: int | None, avg_dist: float | None, gfr: float | None,
                  played: int | None, won: int | None) -> np.ndarray:
    win_rate = (won / played) if played and played > 0 and won is not None else None
    log_games = math.log1p(played) if played and played > 0 else None
    raw = [rating, moving, nomove, nmpz, avg_dist, gfr, win_rate, log_games]
    return np.array(
        [float(v) if v is not None else np.nan for v in raw], dtype=np.float64
    )


def _load_rows(db: Session, cutoff: datetime) -> list[_Row]:
    sql = text("""
        SELECT DISTINCT ON (rs.account_id)
            rs.account_id, a.country_code,
            rs.rating, rs.rating_moving, rs.rating_nomove, rs.rating_nmpz,
            rs.avg_guess_distance_km, rs.guessed_first_rate,
            rs.games_played, rs.games_won
        FROM rating_snapshots rs
        JOIN accounts a ON a.id = rs.account_id
        WHERE a.tracked = true AND rs.rating IS NOT NULL AND rs.captured_at >= :cutoff
        ORDER BY rs.account_id, rs.captured_at DESC
    """)
    rows: list[_Row] = []
    for r in db.execute(sql, {"cutoff": cutoff}).fetchall():
        feats = _row_features(
            r.rating, r.rating_moving, r.rating_nomove, r.rating_nmpz,
            r.avg_guess_distance_km, r.guessed_first_rate,
            r.games_played, r.games_won,
        )
        rows.append(_Row(account_id=r.account_id, country_code=r.country_code, features=feats))
    return rows


def _normalize_and_weight(matrix: np.ndarray) -> np.ndarray:
    """MinMax-normalize each column (NaN-aware), impute missing with column mean (0.5), apply weights."""
    out = matrix.copy()
    for col in range(out.shape[1]):
        c = out[:, col]
        valid = ~np.isnan(c)
        if not valid.any():
            out[:, col] = 0.0
            continue
        lo = float(np.min(c[valid]))
        hi = float(np.max(c[valid]))
        rng = hi - lo
        if rng < 1e-9:
            out[:, col] = 0.0
            continue
        scaled = (c - lo) / rng
        scaled[~valid] = 0.5
        out[:, col] = scaled
    return out * WEIGHTS


def _max_distance() -> float:
    return float(np.linalg.norm(WEIGHTS))


def _similarity(d: float) -> int:
    sim = 100.0 * (1.0 - d / _max_distance())
    return int(round(max(0.0, min(100.0, sim))))


def compute_matches(db: Session, cutoff: datetime) -> int:
    rows = _load_rows(db, cutoff)
    if len(rows) < 2:
        log.info("doppelganger: not enough players (%d)", len(rows))
        return 0

    raw = np.vstack([r.features for r in rows])
    weighted = _normalize_and_weight(raw)

    knn = NearestNeighbors(n_neighbors=2, algorithm="auto")
    knn.fit(weighted)
    distances, indices = knn.kneighbors(weighted, n_neighbors=2)

    country_to_idx: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        if r.country_code:
            country_to_idx.setdefault(r.country_code, []).append(i)

    country_knns: dict[str, tuple[NearestNeighbors, list[int]]] = {}
    for cc, idxs in country_to_idx.items():
        if len(idxs) < 2:
            continue
        sub = weighted[idxs]
        sk = NearestNeighbors(n_neighbors=2, algorithm="auto")
        sk.fit(sub)
        country_knns[cc] = (sk, idxs)

    now = datetime.now(UTC)
    db.execute(text("DELETE FROM player_matches"))
    db.flush()

    written = 0
    batch: list[PlayerMatch] = []
    for i, r in enumerate(rows):
        # global: nearest excluding self
        g_idx = int(indices[i][1]) if int(indices[i][0]) == i else int(indices[i][0])
        g_dist = float(distances[i][1] if int(indices[i][0]) == i else distances[i][0])
        global_match_id = rows[g_idx].account_id
        global_sim = _similarity(g_dist)

        country_match_id: str | None = None
        country_sim: int | None = None
        if r.country_code and r.country_code in country_knns:
            sk, idxs = country_knns[r.country_code]
            local_pos = idxs.index(i)
            d2, ix2 = sk.kneighbors([weighted[i]], n_neighbors=2)
            l_idx = int(ix2[0][1]) if int(ix2[0][0]) == local_pos else int(ix2[0][0])
            l_dist = float(d2[0][1] if int(ix2[0][0]) == local_pos else d2[0][0])
            country_match_id = rows[idxs[l_idx]].account_id
            country_sim = _similarity(l_dist)

        batch.append(PlayerMatch(
            account_id=r.account_id,
            global_match_id=global_match_id,
            global_similarity=global_sim,
            country_match_id=country_match_id,
            country_similarity=country_sim,
            computed_at=now,
        ))
        written += 1
        if len(batch) >= 500:
            db.bulk_save_objects(batch)
            db.flush()
            batch.clear()
    if batch:
        db.bulk_save_objects(batch)
    db.commit()
    log.info("doppelganger: wrote %d matches", written)
    return written
