from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from geostats.client import GeoClient
from geostats.db import session_scope
from geostats.models import Account, RatingSnapshot
from geostats.state import set_ncfa


def _make_client(ncfa_cookie: str) -> GeoClient:
    return GeoClient(ncfa_cookie, on_cookie_change=set_ncfa)

log = logging.getLogger(__name__)


async def discover_leaderboard(client: GeoClient, limit: int = 100, max_total: int = 200) -> list[str]:
    all_ids: list[str] = []
    offset = 0
    while True:
        remaining = max_total - len(all_ids)
        page_size = min(limit, remaining)
        page = await client.get_leaderboard_page(offset=offset, limit=page_size)
        if not page:
            break
        all_ids.extend(page)
        if len(all_ids) >= max_total or len(page) < page_size:
            break
        offset += page_size
    return all_ids


def _jitter(base: float) -> float:
    return random.uniform(base * 0.6, base * 2.2)


async def poll_account(client: GeoClient, account_id: str, delay: float = 3.0) -> dict[str, object]:
    progress = await client.get_ranked_progress(account_id)
    await asyncio.sleep(_jitter(delay))
    stats = await client.get_user_stats(account_id)
    await asyncio.sleep(_jitter(delay))

    gm = progress.game_mode_ratings
    dt = stats.duels_total

    return {
        "account_id": account_id,
        "captured_at": datetime.now(UTC),
        "rating": progress.rating,
        "division_number": progress.division_number,
        "division_name": progress.division_name,
        "win_streak": progress.win_streak,
        "guessed_first_rate": progress.guessed_first_rate,
        "rating_moving": gm.moving if gm else None,
        "rating_nomove": gm.nomove if gm else None,
        "rating_nmpz": gm.nmpz if gm else None,
        "games_played": dt.num_games_played or None,
        "games_won": dt.num_wins or None,
        "avg_guess_distance_km": (dt.avg_guess_distance / 1000) if dt.avg_guess_distance else None,
    }


def _upsert_accounts(ids: list[str]) -> set[str]:
    now = datetime.now(UTC)
    unique_ids = list(dict.fromkeys(ids))
    with session_scope() as db:
        existing = {row.id for row in db.query(Account.id).all()}
        new_ids = {uid for uid in unique_ids if uid not in existing}
        if unique_ids:
            db.execute(
                pg_insert(Account).on_conflict_do_update(
                    index_elements=["id"], set_={"tracked": True}
                ),
                [
                    {
                        "id": uid, "nick": uid, "country_code": None, "level": None,
                        "is_pro": False, "pin_url": None, "tracked": True,
                        "created_at": now, "last_polled_at": None, "last_error": None,
                        "lookup_count": 0,
                    }
                    for uid in unique_ids
                ],
            )
            db.query(Account).filter(
                Account.id.notin_(unique_ids), Account.tracked == True  # noqa: E712
            ).update({"tracked": False}, synchronize_session=False)
    return new_ids


async def _run_poll(
    client: GeoClient, account_ids: list[str], delay: float, fetch_info_ids: set[str]
) -> None:
    today_utc = datetime.now(UTC).date()
    with session_scope() as db:
        rows = db.query(Account.id, Account.last_polled_at).filter(Account.id.in_(account_ids)).all()
    polled_today = {r.id for r in rows if r.last_polled_at is not None and r.last_polled_at.date() == today_utc}

    ids = [aid for aid in account_ids if aid not in polled_today]
    if polled_today:
        log.debug("skipping %d accounts already polled today", len(polled_today))
    random.shuffle(ids)
    next_break = random.randint(30, 60)
    for i, account_id in enumerate(ids):
        if i == next_break:
            pause = random.uniform(45, 120)
            log.debug("session pause %.0fs after %d accounts", pause, i)
            await asyncio.sleep(pause)
            next_break += random.randint(30, 60)
        try:
            snapshot = await poll_account(client, account_id, delay=delay)
            fetch_profile = account_id in fetch_info_ids
            if fetch_profile:
                info = await client.get_user_info(account_id)
                await asyncio.sleep(_jitter(delay))
                with session_scope() as db:
                    db.query(Account).filter(Account.id == account_id).update({
                        "nick": info.nick,
                        "country_code": info.country_code,
                        "is_pro": info.is_pro,
                        "level": info.level,
                        "pin_url": info.pin_url,
                    })
            with session_scope() as db:
                db.merge(RatingSnapshot(**snapshot))
                db.query(Account).filter(Account.id == account_id).update({
                    "last_polled_at": snapshot["captured_at"],
                    "last_error": None,
                })
            log.info("polled %s", account_id)
        except Exception as exc:
            log.warning("failed to poll %s: %s", account_id, exc)
            with session_scope() as db:
                db.query(Account).filter(Account.id == account_id).update(
                    {"last_error": str(exc)}
                )


async def run_discover(ncfa_cookie: str) -> None:
    async with _make_client(ncfa_cookie) as client:
        ids = await discover_leaderboard(client, limit=100)
    log.info("discovered %d rated players", len(ids))
    new_ids = _upsert_accounts(ids)
    log.info("new accounts added: %d", len(new_ids))


async def run_full_poll(ncfa_cookie: str, delay: float) -> None:
    from geostats.ranker import compute_ranks  # noqa: PLC0415

    async with _make_client(ncfa_cookie) as client:
        ids = await discover_leaderboard(client, limit=100)
        log.info("discovered %d rated players", len(ids))
        new_ids = _upsert_accounts(ids)
        unique_ids = list(dict.fromkeys(ids))
        with session_scope() as db:
            no_pin = {
                row.id for row in db.query(Account.id)
                .filter(Account.id.in_(unique_ids), Account.pin_url.is_(None))
                .all()
            }
        await _run_poll(client, unique_ids, delay, new_ids | no_pin)

    with session_scope() as db:
        compute_ranks(db)
    log.info("ranks computed")


async def run_new_poll(ncfa_cookie: str, delay: float, limit: int | None = None) -> None:
    from geostats.ranker import compute_ranks  # noqa: PLC0415

    with session_scope() as db:
        q = (
            db.query(Account.id)
            .filter(Account.tracked == True, Account.last_polled_at.is_(None))  # noqa: E712
            .order_by(Account.created_at.desc())
        )
        if limit is not None:
            q = q.limit(limit)
        new_ids = [row.id for row in q.all()]

    log.info("new accounts to poll: %d (limit=%s)", len(new_ids), limit)
    if not new_ids:
        return

    async with _make_client(ncfa_cookie) as client:
        await _run_poll(client, new_ids, delay, set(new_ids))  # all new → fetch info

    with session_scope() as db:
        compute_ranks(db)
    log.info("new accounts polled and ranks computed")


async def run_top_poll(ncfa_cookie: str, delay: float, limit: int) -> None:
    from geostats.ranker import compute_ranks  # noqa: PLC0415

    with session_scope() as db:
        rows = db.execute(text("""
            SELECT DISTINCT ON (rs.account_id) rs.account_id, rs.rating
            FROM rating_snapshots rs
            JOIN accounts a ON a.id = rs.account_id
            WHERE a.tracked = true AND rs.rating IS NOT NULL
            ORDER BY rs.account_id, rs.captured_at DESC
        """)).fetchall()

        lookup_ids = {
            row.id for row in db.query(Account.id)
            .filter(Account.lookup_count > 0, Account.tracked == True)  # noqa: E712
            .all()
        }

    top_ids = [
        r.account_id
        for r in sorted(rows, key=lambda r: -(r.rating or 0))[:limit]
    ]
    all_ids = list(dict.fromkeys(top_ids + list(lookup_ids)))
    log.info("top-%d poll: %d accounts (%d from lookups)", limit, len(all_ids), len(lookup_ids))

    with session_scope() as db:
        no_pin = {
            row.id for row in db.query(Account.id)
            .filter(Account.id.in_(all_ids), Account.pin_url.is_(None))
            .all()
        }

    async with _make_client(ncfa_cookie) as client:
        await _run_poll(client, all_ids, delay, no_pin)

    with session_scope() as db:
        compute_ranks(db)
    log.info("ranks computed")
