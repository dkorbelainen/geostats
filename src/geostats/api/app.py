from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def create_app() -> FastAPI:
    app = FastAPI(title="GeoStats")

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    from geostats.api.routes import router  # noqa: PLC0415

    app.include_router(router)
    return app
