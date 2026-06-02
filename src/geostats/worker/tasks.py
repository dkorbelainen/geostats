from typing import Any, Literal, cast

from geostats.db import session_scope
from geostats.models import Account, RatingSnapshot
from geostats.stats.forecast import forecast_rating
from geostats.worker.celery_app import celery_app

_Mode = Literal["overall", "moving", "nomove", "nmpz"]


@celery_app.task
def compute_forecast(user_id: str, mode: str, horizon: int) -> dict[str, Any]:
    """Run forecast computation in a Celery worker."""
    with session_scope() as db:
        account = db.get(Account, user_id)
        if account is None:
            raise ValueError(f"account {user_id!r} not found")
        snaps: list[RatingSnapshot] = (
            db.query(RatingSnapshot)
            .filter(RatingSnapshot.account_id == user_id)
            .order_by(RatingSnapshot.captured_at.asc())
            .all()
        )
        result = forecast_rating(snaps, cast(_Mode, mode), horizon)
        return {
            "horizon": result.horizon_days,
            "mode": mode,
            "predicted_delta": result.predicted_delta,
            "predicted_rating": result.predicted_rating,
            "confidence": result.confidence,
            "n_points": result.n_points,
        }
