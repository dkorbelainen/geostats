from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field

_BASE = "https://www.geoguessr.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.geoguessr.com/",
    "Origin": "https://www.geoguessr.com",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

log = logging.getLogger(__name__)


class UserInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    nick: str
    country_code: str | None = Field(None, alias="countryCode")
    is_pro: bool = Field(False, alias="isProUser")
    level: int | None = None
    pin_url: str | None = None

    @classmethod
    def from_response(cls, data: dict[str, object]) -> UserInfo:
        pin: dict[str, object] = data.get("pin") or {}  # type: ignore[assignment]
        progress: dict[str, object] = data.get("progress") or {}  # type: ignore[assignment]
        return cls(
            id=data["id"],
            nick=data["nick"],
            countryCode=data.get("countryCode"),
            isProUser=data.get("isProUser", False),
            level=progress.get("level"),
            pin_url=pin.get("url"),
        )


class GameModeRatings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    moving: int | None = Field(None, alias="Standardduels")
    nomove: int | None = Field(None, alias="Nomoveduels")
    nmpz: int | None = Field(None, alias="Nmpzduels")


class RankedProgress(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rating: int | None = None
    division_number: int | None = Field(None, alias="divisionNumber")
    division_name: str | None = Field(None, alias="divisionName")
    win_streak: int | None = Field(None, alias="winStreak")
    guessed_first_rate: float | None = Field(None, alias="guessedFirstRate")
    game_mode_ratings: GameModeRatings | None = Field(None, alias="gameModeRatings")


class DuelStats(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    num_games_played: int = Field(0, alias="numGamesPlayed")
    num_wins: int = Field(0, alias="numWins")
    win_ratio: float = Field(0.0, alias="winRatio")
    avg_guess_distance: float = Field(0.0, alias="avgGuessDistance")


class UserStats(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    duels_total: DuelStats = Field(default_factory=DuelStats, alias="duelsTotal")


class SearchResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId")
    nick: str


class GeoClient:
    def __init__(
        self,
        ncfa_cookie: str,
        on_cookie_change: Callable[[str], None] | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=_BASE,
            headers=_HEADERS,
            cookies={"_ncfa": ncfa_cookie},
            timeout=30.0,
            follow_redirects=True,
        )
        self._on_cookie_change = on_cookie_change
        self._last_ncfa = ncfa_cookie

    async def __aenter__(self) -> GeoClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        self._sync_cookie()
        await self._client.aclose()

    def _sync_cookie(self) -> None:
        current = self._client.cookies.get("_ncfa")
        if current and current != self._last_ncfa:
            self._last_ncfa = current
            if self._on_cookie_change:
                try:
                    self._on_cookie_change(current)
                except Exception as exc:
                    log.warning("ncfa persist callback failed: %s", exc)

    async def _get(self, url: str, **kwargs: object) -> httpx.Response:
        """GET with 429 backoff retry."""
        for attempt in range(4):
            r = await self._client.get(url, **kwargs)  # type: ignore[arg-type]
            if r.status_code == 429:
                wait = (2 ** attempt) * 20 + random.uniform(5, 15)
                log.warning("429 rate-limited on %s, waiting %.0fs", url, wait)
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            self._sync_cookie()
            return r
        r.raise_for_status()
        return r

    async def get_user_info(self, user_id: str) -> UserInfo:
        r = await self._get(f"/api/v3/users/{user_id}")
        return UserInfo.from_response(r.json())

    async def get_ranked_progress(self, user_id: str) -> RankedProgress:
        r = await self._get(f"/api/v4/ranked-system/progress/{user_id}")
        return RankedProgress.model_validate(r.json())

    async def get_user_stats(self, user_id: str) -> UserStats:
        r = await self._get(f"/api/v4/stats/users/{user_id}")
        return UserStats.model_validate(r.json())

    async def get_leaderboard_page(self, offset: int, limit: int = 100) -> list[str]:
        r = await self._get(
            "/api/v4/ranked-system/ratings",
            params={"offset": offset, "limit": limit},
        )
        return [entry["userId"] for entry in r.json()]

    async def search_user(self, nick: str) -> list[SearchResult]:
        r = await self._get("/api/v3/search/user", params={"q": nick})
        data = r.json()
        if isinstance(data, list):
            return [SearchResult.model_validate(u) for u in data]
        return []
