import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def compute_ranks(db: Session) -> None:
    result = db.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (rs.account_id)
                rs.account_id,
                rs.captured_at,
                rs.rating,
                rs.rating_moving,
                rs.rating_nomove,
                rs.rating_nmpz
            FROM rating_snapshots rs
            JOIN accounts a ON a.id = rs.account_id
            WHERE a.last_polled_at IS NOT NULL
            ORDER BY rs.account_id, rs.captured_at DESC
        ),
        ranked AS (
            SELECT
                l.account_id,
                l.captured_at,
                l.rating,
                l.rating_moving,
                l.rating_nomove,
                l.rating_nmpz,
                RANK() OVER (ORDER BY l.rating        DESC NULLS LAST) AS pos_overall,
                RANK() OVER (ORDER BY l.rating_moving DESC NULLS LAST) AS pos_moving,
                RANK() OVER (ORDER BY l.rating_nomove DESC NULLS LAST) AS pos_nomove,
                RANK() OVER (ORDER BY l.rating_nmpz   DESC NULLS LAST) AS pos_nmpz,
                RANK() OVER (
                    PARTITION BY a.country_code
                    ORDER BY l.rating DESC NULLS LAST
                ) AS pos_country
            FROM latest l
            JOIN accounts a ON a.id = l.account_id
        )
        UPDATE rating_snapshots rs
        SET
            position_overall = CASE WHEN r.rating         IS NOT NULL THEN r.pos_overall ELSE NULL END,
            position_moving  = CASE WHEN r.rating_moving  IS NOT NULL THEN r.pos_moving  ELSE NULL END,
            position_nomove  = CASE WHEN r.rating_nomove  IS NOT NULL THEN r.pos_nomove  ELSE NULL END,
            position_nmpz    = CASE WHEN r.rating_nmpz    IS NOT NULL THEN r.pos_nmpz    ELSE NULL END,
            position_country = CASE WHEN r.rating         IS NOT NULL THEN r.pos_country ELSE NULL END
        FROM ranked r
        WHERE rs.account_id = r.account_id
          AND rs.captured_at = r.captured_at
    """))
    log.info("compute_ranks updated %d snapshot rows", result.rowcount)
    # caller is responsible for commit (session_scope in prod, test fixture rollback in tests)
