from sqlalchemy import text
from sqlalchemy.orm import Session


def compute_ranks(db: Session) -> None:
    db.execute(text("""
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
            WHERE a.tracked = true
            ORDER BY rs.account_id, rs.captured_at DESC
        ),
        ranked AS (
            SELECT
                l.account_id,
                l.captured_at,
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
            position_overall = r.pos_overall,
            position_moving  = r.pos_moving,
            position_nomove  = r.pos_nomove,
            position_nmpz    = r.pos_nmpz,
            position_country = r.pos_country
        FROM ranked r
        WHERE rs.account_id = r.account_id
          AND rs.captured_at = r.captured_at
    """))
    # caller is responsible for commit (session_scope in prod, test fixture rollback in tests)
