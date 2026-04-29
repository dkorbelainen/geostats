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
def poll_discover() -> None:
    cookie = _require_ncfa()
    from geostats.poller import run_discover  # noqa: PLC0415
    asyncio.run(run_discover(ncfa_cookie=cookie))


@cli.command("poll-new")
def poll_new() -> None:
    cookie = _require_ncfa()
    settings = get_settings()
    from geostats.poller import run_new_poll  # noqa: PLC0415
    asyncio.run(run_new_poll(
        ncfa_cookie=cookie,
        delay=settings.poll_request_delay_sec,
    ))
