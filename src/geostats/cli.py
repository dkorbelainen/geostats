import asyncio
import logging

import click

from geostats.config import get_settings
from geostats.db import session_factory
from geostats.state import get_ncfa

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _require_ncfa() -> str:
    session_factory()
    cookie = get_ncfa()
    if not cookie:
        raise click.ClickException(
            "ncfa cookie not available; set GEOGUESSR_NCFA_COOKIE for first-run bootstrap"
        )
    return cookie


@click.group()
def cli() -> None:
    pass


@cli.command("poll-full")
def poll_full() -> None:
    cookie = _require_ncfa()
    settings = get_settings()
    from geostats.poller import run_full_poll  # noqa: PLC0415
    asyncio.run(run_full_poll(
        ncfa_cookie=cookie,
        delay=settings.poll_request_delay_sec,
    ))


@cli.command("poll-top")
@click.option(
    "--limit",
    default=2000,
    show_default=True,
    type=int,
    help="Number of top-rated accounts to poll",
)
def poll_top(limit: int) -> None:
    cookie = _require_ncfa()
    settings = get_settings()
    from geostats.poller import run_top_poll  # noqa: PLC0415
    asyncio.run(run_top_poll(
        ncfa_cookie=cookie,
        delay=settings.poll_request_delay_sec,
        limit=limit,
    ))


@cli.command("poll-discover")
@click.option(
    "--limit",
    default=1000,
    show_default=True,
    type=int,
    help="Max accounts to discover from global leaderboard (top-N by rating)",
)
def poll_discover(limit: int) -> None:
    cookie = _require_ncfa()
    from geostats.poller import run_discover  # noqa: PLC0415
    asyncio.run(run_discover(ncfa_cookie=cookie, max_total=limit))


@cli.command("compute-matches")
def compute_matches_cmd() -> None:
    """Recompute doppelganger matches for all tracked accounts."""
    session_factory()
    from geostats.db import session_scope  # noqa: PLC0415
    from geostats.stats.doppelganger import compute_matches  # noqa: PLC0415
    with session_scope() as db:
        n = compute_matches(db)
    click.echo(f"computed matches for {n} players")


@cli.command("rerank")
def rerank() -> None:
    """Recompute position rankings for all tracked accounts."""
    session_factory()
    from geostats.db import session_scope  # noqa: PLC0415
    from geostats.ranker import compute_ranks  # noqa: PLC0415
    with session_scope() as db:
        compute_ranks(db)
    click.echo("ranks recomputed")
    
@cli.command("compute-anomalies")
def compute_anomalies_cmd() -> None:
    """Recompute account anomaly scores for all eligible tracked accounts."""
    from geostats.db import session_factory as _sf, session_scope  # noqa: PLC0415
    from geostats.stats.anomalies import compute_anomalies  # noqa: PLC0415
    _sf()
    with session_scope() as db:
        n = compute_anomalies(db)
    click.echo(f"computed anomalies for {n} players")


@cli.command("poll-new")
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Max accounts per cycle (newest first); omit for unbounded",
)
def poll_new(limit: int | None) -> None:
    cookie = _require_ncfa()
    settings = get_settings()
    from geostats.poller import run_new_poll  # noqa: PLC0415
    asyncio.run(run_new_poll(
        ncfa_cookie=cookie,
        delay=settings.poll_request_delay_sec,
        limit=limit,
    ))
