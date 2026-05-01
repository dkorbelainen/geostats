from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from geostats.db import Base


class AppState(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    nick: Mapped[str] = mapped_column(Text)
    slug: Mapped[str | None] = mapped_column(Text, unique=True, default=None)
    country_code: Mapped[str | None] = mapped_column(Text, default=None)
    level: Mapped[int | None] = mapped_column(Integer, default=None)
    is_pro: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_url: Mapped[str | None] = mapped_column(Text, default=None)
    avatar_url: Mapped[str | None] = mapped_column(Text, default=None)
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    lookup_count: Mapped[int] = mapped_column(Integer, server_default="0")

    def __init__(
        self,
        id: str,
        nick: str,
        created_at: datetime,
        slug: str | None = None,
        country_code: str | None = None,
        level: int | None = None,
        is_pro: bool = False,
        pin_url: str | None = None,
        avatar_url: str | None = None,
        tracked: bool = True,
        last_polled_at: datetime | None = None,
        last_error: str | None = None,
        lookup_count: int = 0,
    ):
        self.id = id
        self.nick = nick
        self.slug = slug
        self.created_at = created_at
        self.country_code = country_code
        self.level = level
        self.is_pro = is_pro
        self.pin_url = pin_url
        self.avatar_url = avatar_url
        self.tracked = tracked
        self.last_polled_at = last_polled_at
        self.last_error = last_error
        self.lookup_count = lookup_count


class RatingSnapshot(Base):
    __tablename__ = "rating_snapshots"

    account_id: Mapped[str] = mapped_column(
        Text, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    rating: Mapped[int | None] = mapped_column(Integer)
    division_number: Mapped[int | None] = mapped_column(Integer)
    division_name: Mapped[str | None] = mapped_column(Text)

    rating_moving: Mapped[int | None] = mapped_column(Integer)
    rating_nomove: Mapped[int | None] = mapped_column(Integer)
    rating_nmpz: Mapped[int | None] = mapped_column(Integer)

    win_streak: Mapped[int | None] = mapped_column(Integer)
    guessed_first_rate: Mapped[float | None] = mapped_column(Float)

    games_played: Mapped[int | None] = mapped_column(Integer)
    games_won: Mapped[int | None] = mapped_column(Integer)
    avg_guess_distance_km: Mapped[float | None] = mapped_column(Float)

    position_overall: Mapped[int | None] = mapped_column(Integer)
    position_moving: Mapped[int | None] = mapped_column(Integer)
    position_nomove: Mapped[int | None] = mapped_column(Integer)
    position_nmpz: Mapped[int | None] = mapped_column(Integer)
    position_country: Mapped[int | None] = mapped_column(Integer)
