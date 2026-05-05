# tests/test_migration_008.py
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from geostats.models import Account

_CLEANUP_SQL = text("""
    UPDATE accounts SET slug = NULL
    WHERE slug IS NOT NULL
      AND slug !~ '^[a-z0-9_а-яё-]+$'
""")


def _make_account(id_: str, nick: str, slug: str | None) -> Account:
    a = Account(id=id_, nick=nick, created_at=datetime.now(UTC))
    a.slug = slug
    return a


def test_migration_clears_emoji_slug(db: Session) -> None:
    db.add(_make_account("a1", "🐈‍⬛", "🐈‍⬛"))
    db.add(_make_account("a2", "normal", "normal"))
    db.add(_make_account("a3", "𝓝𝓲𝓰𝓱𝓽", "𝓝𝓲𝓰𝓱𝓽"))
    db.add(_make_account("a4", "twitch.tv/yap", "twitchtv_yap"))
    db.add(_make_account("a5", "slash/name", "slash/name"))
    db.commit()

    db.execute(_CLEANUP_SQL)
    db.commit()

    slugs = {a.id: a.slug for a in db.query(Account).all()}
    assert slugs["a1"] is None      # emoji cleared
    assert slugs["a2"] == "normal"  # valid preserved
    assert slugs["a3"] is None      # math unicode cleared
    assert slugs["a4"] == "twitchtv_yap"  # already clean slug preserved
    assert slugs["a5"] is None      # slash cleared
