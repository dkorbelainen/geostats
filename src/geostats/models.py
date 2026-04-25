from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from geostats.db import Base


class GameMode(StrEnum):
    DUELS = "duels"
    TEAM_DUELS = "team_duels"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    nick: Mapped[str] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(Text)
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class RatingSnapshot(Base):
    __tablename__ = "rating_snapshots"

    account_id: Mapped[str] = mapped_column(
        Text, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[GameMode] = mapped_column(
        SAEnum(GameMode, values_callable=lambda obj: [e.value for e in obj], native_enum=False),
        primary_key=True,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    games_played: Mapped[int | None] = mapped_column(Integer)
