from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert

from geostats.config import get_settings
from geostats.db import session_scope
from geostats.models import AppState

log = logging.getLogger(__name__)

NCFA_KEY = "geoguessr_ncfa"


def get_ncfa() -> str | None:
    """Return persisted ncfa, falling back to env on first run (and seeding DB)."""
    with session_scope() as db:
        row = db.get(AppState, NCFA_KEY)
        if row is not None:
            return row.value
    env_value = get_settings().geoguessr_ncfa_cookie
    if env_value:
        set_ncfa(env_value)
        return env_value
    return None


def set_ncfa(value: str) -> None:
    if not value:
        return
    now = datetime.now(UTC)
    with session_scope() as db:
        stmt = pg_insert(AppState).values(key=NCFA_KEY, value=value, updated_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": value, "updated_at": now}
        )
        db.execute(stmt)
    log.debug("ncfa cookie persisted")
