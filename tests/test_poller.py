from unittest.mock import AsyncMock, MagicMock

import pytest

from geostats.client import RankedProgress, UserStats
from geostats.poller import discover_leaderboard, poll_account


@pytest.mark.asyncio
async def test_discover_leaderboard_paginates():
    client = MagicMock()
    client.get_leaderboard_page = AsyncMock(
        side_effect=[
            ["id1", "id2"],  # page 0 — full page, continue
            ["id3"],         # page 1 — partial, stop
        ]
    )
    result = await discover_leaderboard(client, limit=2)
    assert result == ["id1", "id2", "id3"]
    assert client.get_leaderboard_page.call_count == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_discover_leaderboard_empty():
    client = MagicMock()
    client.get_leaderboard_page = AsyncMock(return_value=[])
    result = await discover_leaderboard(client)
    assert result == []
    client.get_leaderboard_page.assert_called_once()


@pytest.mark.asyncio
async def test_poll_account_builds_snapshot():
    progress = RankedProgress.model_validate({
        "rating": 1500,
        "divisionNumber": 15,
        "divisionName": "Gold III",
        "winStreak": 3,
        "guessedFirstRate": 0.65,
        "gameModeRatings": {
            "standardDuels": 1550,
            "noMoveDuels": 1400,
            "nmpzDuels": 1200,
        },
    })
    stats = UserStats.model_validate({
        "duelsTotal": {
            "numGamesPlayed": 100,
            "numWins": 65,
            "winRatio": 0.65,
            "avgGuessDistance": 500000.0,
        }
    })
    client = MagicMock()
    client.get_ranked_progress = AsyncMock(return_value=progress)
    client.get_user_stats = AsyncMock(return_value=stats)

    snapshot = await poll_account(client, "abc123", delay=0)

    assert snapshot["account_id"] == "abc123"
    assert snapshot["rating"] == 1500  # noqa: PLR2004
    assert snapshot["rating_moving"] == 1550  # noqa: PLR2004
    assert snapshot["rating_nomove"] == 1400  # noqa: PLR2004
    assert snapshot["rating_nmpz"] == 1200  # noqa: PLR2004
    assert snapshot["games_played"] == 100  # noqa: PLR2004
    assert snapshot["games_won"] == 65  # noqa: PLR2004
    assert snapshot["avg_guess_distance_km"] == pytest.approx(500.0)
    assert "captured_at" in snapshot


@pytest.mark.asyncio
async def test_poll_account_handles_null_game_mode_ratings():
    progress = RankedProgress.model_validate({
        "divisionNumber": 7,
        "divisionName": "Silver I",
        "rating": None,
        "winStreak": 1,
        "guessedFirstRate": 0.52,
    })
    stats = UserStats.model_validate({
        "duelsTotal": {"numGamesPlayed": 0, "numWins": 0, "winRatio": 0.0, "avgGuessDistance": 0.0}
    })
    client = MagicMock()
    client.get_ranked_progress = AsyncMock(return_value=progress)
    client.get_user_stats = AsyncMock(return_value=stats)

    snapshot = await poll_account(client, "xyz", delay=0)

    assert snapshot["rating"] is None
    assert snapshot["rating_moving"] is None
    assert snapshot["games_played"] is None
