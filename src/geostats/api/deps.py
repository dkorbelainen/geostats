from collections.abc import AsyncIterator, Iterator
from datetime import datetime

from sqlalchemy.orm import Session

from geostats.client import GeoClient
from geostats.config import get_settings
from geostats.db import session_factory
from geostats.state import get_ncfa, set_ncfa


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


async def get_geo_client() -> AsyncIterator[GeoClient]:
    cookie = get_ncfa() or ""
    async with GeoClient(ncfa_cookie=cookie, on_cookie_change=set_ncfa) as client:
        yield client


def get_rating_cutoff() -> datetime:
    return get_settings().rating_system_cutoff
