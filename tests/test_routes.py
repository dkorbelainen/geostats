from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from geostats.api.app import create_app
from geostats.api.deps import get_db
from geostats.models import Account, RatingSnapshot


@pytest.fixture
def client(db: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _account(
    id: str = "abcdefghij1234567890",
    *,
    polled: bool = False,
) -> Account:
    return Account(
        id=id,
        nick="testplayer",
        created_at=_now(),
        last_polled_at=_now() if polled else None,
    )


def _snap(account_id: str, *, days_ago: int = 1, rating: int = 2000) -> RatingSnapshot:
    return RatingSnapshot(
        account_id=account_id,
        captured_at=_now() - timedelta(days=days_ago),
        rating=rating,
    )


# ── /healthz ──────────────────────────────────────────────────────────────────

def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── / ─────────────────────────────────────────────────────────────────────────

def test_landing_contains_geostats(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "GeoStats" in r.text


# ── /lookup ───────────────────────────────────────────────────────────────────

def test_lookup_valid_url_redirects_and_creates_account(
    client: TestClient, db: Session
) -> None:
    r = client.post(
        "/lookup",
        data={"profile": "https://www.geoguessr.com/user/abcdefghij1234567890"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/profile/abcdefghij1234567890"
    assert db.get(Account, "abcdefghij1234567890") is not None


def test_lookup_valid_raw_id_redirects(client: TestClient) -> None:
    r = client.post(
        "/lookup",
        data={"profile": "abcdefghij1234567890"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/profile/abcdefghij1234567890" in r.headers["location"]


def test_lookup_invalid_returns_400(client: TestClient) -> None:
    r = client.post("/lookup", data={"profile": "not-valid"})
    assert r.status_code == 400
    assert "GeoStats" in r.text


def test_lookup_existing_account_no_duplicate(client: TestClient, db: Session) -> None:
    db.add(_account())
    db.flush()
    r = client.post(
        "/lookup",
        data={"profile": "abcdefghij1234567890"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    count = db.query(Account).filter(Account.id == "abcdefghij1234567890").count()
    assert count == 1


# ── /profile/{id} ─────────────────────────────────────────────────────────────

def test_profile_collecting_state(client: TestClient, db: Session) -> None:
    db.add(_account())
    db.flush()
    r = client.get("/profile/abcdefghij1234567890")
    assert r.status_code == 200
    assert "Collecting" in r.text


def test_profile_with_snapshots_shows_rating(client: TestClient, db: Session) -> None:
    db.add(_account(polled=True))
    db.flush()
    db.add(_snap("abcdefghij1234567890", rating=2347))
    db.flush()
    r = client.get("/profile/abcdefghij1234567890")
    assert r.status_code == 200
    assert "2" in r.text


def test_profile_not_found(client: TestClient) -> None:
    r = client.get("/profile/abcdefghij1234567890")
    assert r.status_code == 404


def test_profile_invalid_id_returns_404(client: TestClient) -> None:
    r = client.get("/profile/tooshort")
    assert r.status_code == 404


# ── /api/profile/{id}/series ──────────────────────────────────────────────────

def test_series_returns_points(client: TestClient, db: Session) -> None:
    db.add(_account(polled=True))
    db.flush()
    db.add(_snap("abcdefghij1234567890", days_ago=5, rating=2200))
    db.flush()
    r = client.get("/api/profile/abcdefghij1234567890/series?mode=overall&range=30d")
    assert r.status_code == 200
    data = r.json()
    assert "points" in data
    assert data["points"][0][1] == 2200


def test_series_default_params(client: TestClient, db: Session) -> None:
    db.add(_account(polled=True))
    db.flush()
    r = client.get("/api/profile/abcdefghij1234567890/series")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "overall"
    assert data["range"] == "30d"


def test_series_unknown_account_returns_404(client: TestClient) -> None:
    r = client.get("/api/profile/abcdefghij1234567890/series")
    assert r.status_code == 404


def test_series_invalid_mode_returns_422(client: TestClient, db: Session) -> None:
    db.add(_account(polled=True))
    db.flush()
    r = client.get("/api/profile/abcdefghij1234567890/series?mode=invalid")
    assert r.status_code == 422
