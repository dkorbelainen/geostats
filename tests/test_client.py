import httpx
import pytest
import respx

from geostats.client import GeoClient

_BASE = "https://www.geoguessr.com"

PROGRESS_JSON = {
    "divisionNumber": 15,
    "divisionName": "Gold III",
    "rating": 1500,
    "winStreak": 3,
    "guessedFirstRate": 0.65,
    "gameModeRatings": {
        "standardDuels": 1550,
        "noMoveDuels": 1400,
        "nmpzDuels": 1200,
    },
}

STATS_JSON = {
    "duelsTotal": {
        "numGamesPlayed": 100,
        "numWins": 65,
        "winRatio": 0.65,
        "avgGuessDistance": 500000.0,
    },
}

USER_JSON = {
    "id": "abc123",
    "nick": "TestPlayer",
    "countryCode": "us",
    "isProUser": True,
    "progress": {"level": 25},
    "pin": {"url": "pin/abc.png"},
}

LEADERBOARD_JSON = [
    {"userId": "id1", "rating": 2000},
    {"userId": "id2", "rating": 1900},
]

SEARCH_JSON = [
    {"userId": "abc123", "nick": "TestPlayer"},
]


@pytest.fixture
def client():
    return GeoClient(ncfa_cookie="test-cookie")


@pytest.mark.asyncio
async def test_get_ranked_progress(client):
    with respx.mock:
        respx.get(f"{_BASE}/api/v4/ranked-system/progress/abc123").mock(
            return_value=httpx.Response(200, json=PROGRESS_JSON)
        )
        result = await client.get_ranked_progress("abc123")
    assert result.rating == 1500  # noqa: PLR2004
    assert result.division_name == "Gold III"
    assert result.game_mode_ratings is not None
    assert result.game_mode_ratings.moving == 1550  # noqa: PLR2004
    assert result.game_mode_ratings.nomove == 1400  # noqa: PLR2004
    assert result.game_mode_ratings.nmpz == 1200  # noqa: PLR2004


@pytest.mark.asyncio
async def test_get_user_stats(client):
    with respx.mock:
        respx.get(f"{_BASE}/api/v4/stats/users/abc123").mock(
            return_value=httpx.Response(200, json=STATS_JSON)
        )
        result = await client.get_user_stats("abc123")
    assert result.duels_total.num_games_played == 100  # noqa: PLR2004
    assert result.duels_total.num_wins == 65  # noqa: PLR2004
    assert result.duels_total.avg_guess_distance == 500000.0  # noqa: PLR2004


@pytest.mark.asyncio
async def test_get_user_info(client):
    with respx.mock:
        respx.get(f"{_BASE}/api/v3/users/abc123").mock(
            return_value=httpx.Response(200, json=USER_JSON)
        )
        result = await client.get_user_info("abc123")
    assert result.nick == "TestPlayer"
    assert result.country_code == "us"
    assert result.is_pro is True
    assert result.level == 25  # noqa: PLR2004
    assert result.pin_url == "pin/abc.png"


@pytest.mark.asyncio
async def test_get_leaderboard_page(client):
    with respx.mock:
        respx.get(f"{_BASE}/api/v4/ranked-system/ratings").mock(
            return_value=httpx.Response(200, json=LEADERBOARD_JSON)
        )
        result = await client.get_leaderboard_page(offset=0)
    assert result == ["id1", "id2"]


@pytest.mark.asyncio
async def test_get_leaderboard_page_empty(client):
    with respx.mock:
        respx.get(f"{_BASE}/api/v4/ranked-system/ratings").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await client.get_leaderboard_page(offset=9900)
    assert result == []


@pytest.mark.asyncio
async def test_search_user(client):
    with respx.mock:
        respx.get(f"{_BASE}/api/v3/search/user").mock(
            return_value=httpx.Response(200, json=SEARCH_JSON)
        )
        result = await client.search_user("TestPlayer")
    assert len(result) == 1
    assert result[0].nick == "TestPlayer"
    assert result[0].user_id == "abc123"


@pytest.mark.asyncio
async def test_search_user_empty(client):
    with respx.mock:
        respx.get(f"{_BASE}/api/v3/search/user").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await client.search_user("nobody")
    assert result == []
