import asyncio
import logging

import click

from geostats.config import get_settings
from geostats.db import session_factory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@click.group()
def cli() -> None:
    pass


@cli.command("poll-full")
def poll_full() -> None:
    settings = get_settings()
    if not settings.geoguessr_ncfa_cookie:
        raise click.ClickException("GEOGUESSR_NCFA_COOKIE is not set")
    session_factory()
    from geostats.poller import run_full_poll  # noqa: PLC0415
    asyncio.run(run_full_poll(
        ncfa_cookie=settings.geoguessr_ncfa_cookie,
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
    settings = get_settings()
    if not settings.geoguessr_ncfa_cookie:
        raise click.ClickException("GEOGUESSR_NCFA_COOKIE is not set")
    session_factory()
    from geostats.poller import run_top_poll  # noqa: PLC0415
    asyncio.run(run_top_poll(
        ncfa_cookie=settings.geoguessr_ncfa_cookie,
        delay=settings.poll_request_delay_sec,
        limit=limit,
    ))


@cli.command("poll-discover")
def poll_discover() -> None:
    settings = get_settings()
    if not settings.geoguessr_ncfa_cookie:
        raise click.ClickException("GEOGUESSR_NCFA_COOKIE is not set")
    session_factory()
    from geostats.poller import run_discover  # noqa: PLC0415
    asyncio.run(run_discover(ncfa_cookie=settings.geoguessr_ncfa_cookie))


@cli.command("poll-new")
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Max number of new accounts to poll in this run (newest first)",
)
def poll_new(limit: int | None) -> None:
    settings = get_settings()
    if not settings.geoguessr_ncfa_cookie:
        raise click.ClickException("GEOGUESSR_NCFA_COOKIE is not set")
    session_factory()
    from geostats.poller import run_new_poll  # noqa: PLC0415
    asyncio.run(run_new_poll(
        ncfa_cookie=settings.geoguessr_ncfa_cookie,
        delay=settings.poll_request_delay_sec,
        limit=limit,
    ))
