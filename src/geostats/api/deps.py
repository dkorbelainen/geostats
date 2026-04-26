from collections.abc import Iterator

from sqlalchemy.orm import Session

from geostats.db import session_factory


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
