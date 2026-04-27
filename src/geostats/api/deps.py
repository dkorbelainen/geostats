from collections.abc import AsyncIterator, Iterator

from sqlalchemy.orm import Session

from geostats.client import GeoClient
from geostats.config import get_settings
from geostats.db import session_factory


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


async def get_geo_client() -> AsyncIterator[GeoClient]:
    settings = get_settings()
    async with GeoClient(ncfa_cookie=settings.geoguessr_ncfa_cookie or "") as client:
        yield client
