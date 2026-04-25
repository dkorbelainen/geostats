from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from geostats.db import Base


class GameMode(StrEnum):
    DUELS = "duels"
    TEAM_DUELS = "team_duels"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nick: Mapped[str] = mapped_column(String, nullable=False)
    country_code: Mapped[str | None] = mapped_column(String, nullable=True)
    tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RatingSnapshot(Base):
    __tablename__ = "rating_snapshots"

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[GameMode] = mapped_column(String, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    games_played: Mapped[int | None] = mapped_column(Integer, nullable=True)
