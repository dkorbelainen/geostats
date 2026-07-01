from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from geostats.client import RankedProgress, UserInfo, UserStats
from geostats.models import Account, RatingSnapshot
from geostats.poller import discover_leaderboard, poll_account, run_new_poll


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


@pytest.mark.asyncio
async def test_run_new_poll_reaches_compute_ranks(monkeypatch, db):
    """Regression test: compute_ranks() gained a required `cutoff` arg, but
    run_new_poll() (and run_full_poll/run_top_poll) still called it with no
    args, which raised TypeError at runtime. This seeds one never-polled
    tracked account so run_new_poll's `if not new_ids: return` early-out is
    skipped and the trailing `compute_ranks(db, ...)` call actually runs.
    """
    now = datetime.now(UTC)
    db.add(Account(id="new1", nick="new1", tracked=True, created_at=now, last_polled_at=None))
    db.commit()

    @contextmanager
    def fake_scope():
        yield db
        db.flush()  # real session_scope commits; flush makes merges visible without ending the tx

    monkeypatch.setattr("geostats.poller.session_scope", fake_scope)
    monkeypatch.setattr(
        "geostats.config.get_settings",
        lambda: SimpleNamespace(rating_system_cutoff=datetime(2020, 1, 1, tzinfo=UTC)),
    )

    progress = RankedProgress.model_validate({
        "rating": 1500,
        "divisionNumber": 10,
        "divisionName": "Gold I",
        "winStreak": 1,
        "guessedFirstRate": 0.5,
        "gameModeRatings": {"standardDuels": 1500, "noMoveDuels": 1400, "nmpzDuels": 1300},
    })
    stats = UserStats.model_validate({
        "duelsTotal": {
            "numGamesPlayed": 10, "numWins": 5, "winRatio": 0.5, "avgGuessDistance": 100000.0,
        },
    })
    info = UserInfo.model_validate({"id": "new1", "nick": "New1"})

    fake_client = MagicMock()
    fake_client.get_ranked_progress = AsyncMock(return_value=progress)
    fake_client.get_user_stats = AsyncMock(return_value=stats)
    fake_client.get_user_info = AsyncMock(return_value=info)

    @asynccontextmanager
    async def fake_make_client(_ncfa_cookie):
        yield fake_client

    monkeypatch.setattr("geostats.poller._make_client", fake_make_client)

    await run_new_poll("fake-cookie", delay=0)

    account = db.query(Account).filter_by(id="new1").first()
    assert account.last_polled_at is not None

    snapshot = db.query(RatingSnapshot).filter_by(account_id="new1").first()
    assert snapshot is not None
    assert snapshot.position_overall == 1  # noqa: PLR2004 — compute_ranks ran without TypeError
