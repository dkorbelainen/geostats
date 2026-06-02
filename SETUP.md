# GeoStats — Setup & Architecture

GeoStats tracks GeoGuessr player ratings, runs percentile forecasts, detects anomalies, and finds skill-matched doppelgangers via a REST API backed by TimescaleDB.

## Architecture

```
Internet
   │
   ▼
[Caddy :80/:443]  ← reverse proxy, TLS, rate limiting
   │  /api/*  →  [FastAPI :8000]  ← REST API, Pydantic schemas, lifespan
   │                │
   │          [PostgreSQL :5432]  ← TimescaleDB, Alembic migrations
   │
   └── / (static HTML served by Caddy or API)

Networks:
  frontend_net — Caddy ↔ API
  backend_net  — API ↔ PostgreSQL ↔ Poller

Services:
  caddy    — reverse proxy
  api      — FastAPI application
  poller   — background daemon, polls GeoGuessr ratings
  migrate  — one-shot Alembic upgrade
  db       — PostgreSQL / TimescaleDB
```

## Launch

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Notes |
|----------|----------|-------|
| `POSTGRES_USER` | yes | any username |
| `POSTGRES_PASSWORD` | yes | set a real password |
| `POSTGRES_DB` | yes | any db name |
| `DATABASE_URL` | yes | must match the three vars above |
| `GEOGUESSR_NCFA_COOKIE` | for poller only | see below |

**Without `GEOGUESSR_NCFA_COOKIE`**: API, DB, and Caddy start normally. The poller (background data collector) will fail to authenticate and won't collect data, but all API endpoints, health checks, and Swagger UI remain functional. Suitable for evaluating the architecture.

**To obtain `GEOGUESSR_NCFA_COOKIE`**: log in to geoguessr.com in a browser → DevTools → Application → Cookies → copy the value of `_ncfa`.

### 2. Start

The full production stack is defined in `docker-compose.prod.yml` (the default `docker-compose.yml` is a minimal dev overlay for local DB only):

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

Startup order is automatic: `db` → `migrate` → `api` + `poller` → `caddy`. Each step waits for the previous service to pass its healthcheck.

### 3. Verify

```bash
# all containers running
docker compose -f docker-compose.prod.yml ps

# API health (checks DB connectivity)
curl http://localhost:8000/health

# interactive docs
open http://localhost:8000/docs
```

## API Examples

**Health check**
```bash
curl http://localhost:8000/health
# {"status":"ok","db":"ok"}
```

**Look up a player**
```bash
curl -X POST http://localhost:8000/lookup \
  -H "Content-Type: application/json" \
  -d '{"query": "PlayerNick"}'
```

**Rating history**
```bash
curl "http://localhost:8000/api/profile/USER_ID/series?mode=moving"
```

**Percentile forecast**
```bash
curl "http://localhost:8000/api/profile/USER_ID/forecast"
```

**Leaderboard**
```bash
curl "http://localhost:8000/leaderboard?mode=overall&limit=10"
```
