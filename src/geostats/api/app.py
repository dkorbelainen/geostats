import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from geostats.db import session_factory

logger = logging.getLogger(__name__)


# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    session_factory()
    logger.info("startup: db connection pool initialised")
    yield
    logger.info("shutdown: resources released")


def create_app() -> FastAPI:
    app = FastAPI(
        title="GeoStats",
        description="GeoGuessr ranked player statistics and forecasting API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Logging
    @app.middleware("http")
    async def log_request_time(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        logger.info(
            "%s %s %.3fs %d",
            request.method,
            request.url.path,
            elapsed,
            response.status_code,
        )
        return response

    # Error handling
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "status": exc.status_code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "Validation error", "status": 422, "detail": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "status": 500},
        )

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    from geostats.api.routes import router  # noqa: PLC0415

    app.include_router(router)
    return app
