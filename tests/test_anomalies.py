from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from geostats.models import Account, AccountAnomaly


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
