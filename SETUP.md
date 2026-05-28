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

```bash
cp .env.example .env
# edit .env — set POSTGRES_PASSWORD and GEOGUESSR_NCFA_COOKIE

docker compose -f docker-compose.prod.yml up --build -d
```

API available at `http://localhost:8000` (or via Caddy at port 80/443).  
Interactive docs: `http://localhost:8000/docs`

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
