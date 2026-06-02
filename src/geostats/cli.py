import asyncio
import logging
import random
import signal
import time

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
    from geostats.db import session_factory as _sf  # noqa: PLC0415
    from geostats.db import session_scope  # noqa: PLC0415
    from geostats.stats.anomalies import compute_anomalies  # noqa: PLC0415
    _sf()
    with session_scope() as db:
        n = compute_anomalies(db)
    click.echo(f"computed anomalies for {n} players")


# Graceful shutdown
@cli.command("daemon")
def daemon_cmd() -> None:
    """Run the polling loop as a long-lived daemon with clean SIGTERM handling."""
    _shutdown = False

    def _handle_sigterm(signum: int, frame: object) -> None:
        nonlocal _shutdown
        logging.getLogger(__name__).info("SIGTERM received, finishing current cycle then exiting")
        _shutdown = True

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    cookie = _require_ncfa()
    settings = get_settings()
    tick = 0

    from geostats.db import session_scope  # noqa: PLC0415
    from geostats.poller import run_discover, run_new_poll, run_top_poll  # noqa: PLC0415
    from geostats.ranker import compute_ranks  # noqa: PLC0415
    from geostats.stats.anomalies import compute_anomalies  # noqa: PLC0415
    from geostats.stats.doppelganger import compute_matches  # noqa: PLC0415

    log = logging.getLogger(__name__)

    while not _shutdown:
        log.info("daemon tick=%d start", tick)
        asyncio.run(run_top_poll(
            ncfa_cookie=cookie, delay=settings.poll_request_delay_sec, limit=500
        ))
        if tick % 28 == 0:
            asyncio.run(run_discover(ncfa_cookie=cookie, max_total=1000))
            with session_scope() as db:
                compute_matches(db)
                compute_anomalies(db)
                compute_ranks(db)
        asyncio.run(run_new_poll(
            ncfa_cookie=cookie, delay=settings.poll_request_delay_sec, limit=100
        ))
        tick += 1
        if _shutdown:
            break
        sleep_sec = 21600 + random.randint(-1200, 1200)
        log.info("daemon tick=%d done, sleeping %ds", tick - 1, sleep_sec)
        deadline = time.monotonic() + sleep_sec
        while not _shutdown and time.monotonic() < deadline:
            time.sleep(1)

    log.info("daemon exiting cleanly")


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
