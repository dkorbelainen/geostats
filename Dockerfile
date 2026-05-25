FROM python:3.12-slim

# uv dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Layer caching: copy lockfiles first so dep layer rebuilds only when deps change
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project --frozen

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini ./

RUN uv pip install --no-deps .

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
# Graceful shutdown: uvicorn waits up to 30s for in-flight requests on SIGTERM
CMD ["uvicorn", "geostats.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30"]
