from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from geostats.api.app import create_app
from geostats.api.deps import get_db, get_geo_client
from geostats.client import GeoClient, SearchResult
from geostats.models import Account, RatingSnapshot


@pytest.fixture
def mock_geo_client() -> AsyncMock:
    mock = AsyncMock(spec=GeoClient)
    mock.search_user.return_value = []
    return mock


@pytest.fixture
def client(db: Session, mock_geo_client: AsyncMock) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_geo_client] = lambda: mock_geo_client
    return TestClient(app)


def _now() -> datetime:
    return datetime.now(tz=UTC)


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


def test_landing_shows_popular_profiles(client: TestClient, db: Session) -> None:
    acc = Account(
        id="abcdefghij1234567890",
        nick="PopularPlayer",
        created_at=_now(),
        last_polled_at=_now(),
        lookup_count=5,
    )
    db.add(acc)
    db.flush()
    db.add(_snap("abcdefghij1234567890", rating=2500))
    db.flush()
    r = client.get("/")
    assert r.status_code == 200
    assert "PopularPlayer" in r.text
    assert "Most searched" in r.text


def test_account_has_lookup_count(db: Session) -> None:
    acc = _account()
    db.add(acc)
    db.flush()
    assert acc.lookup_count == 0


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


def test_profile_visit_increments_lookup_count(
    client: TestClient, db: Session
) -> None:
    acc = _account(polled=True)
    db.add(acc)
    db.add(_snap("abcdefghij1234567890", rating=2000))
    db.flush()
    client.get("/profile/abcdefghij1234567890")
    db.refresh(acc)
    assert acc.lookup_count == 1


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


def test_lookup_by_nick_creates_account(
    client: TestClient, db: Session, mock_geo_client: AsyncMock
) -> None:
    mock_geo_client.search_user.return_value = [
        SearchResult(user_id="abcdefghij1234567890", nick="RealNick")
    ]
    r = client.post("/lookup", data={"profile": "RealNick"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/profile/abcdefghij1234567890"
    acc = db.get(Account, "abcdefghij1234567890")
    assert acc is not None
    assert acc.nick == "RealNick"


def test_lookup_unknown_nick_returns_400(client: TestClient) -> None:
    # mock_geo_client already returns [] by default
    r = client.post("/lookup", data={"profile": "unknownxyz"})
    assert r.status_code == 400
    assert "GeoStats" in r.text


def test_lookup_increments_lookup_count(
    client: TestClient, db: Session
) -> None:
    acc = _account()
    db.add(acc)
    db.flush()
    client.post(
        "/lookup",
        data={"profile": "abcdefghij1234567890"},
        follow_redirects=False,
    )
    db.refresh(acc)
    assert acc.lookup_count == 1


# ── /api/profile/{id}/forecast ────────────────────────────────────────────────

def test_forecast_unknown_account_returns_404(client: TestClient) -> None:
    r = client.get("/api/profile/abcdefghij1234567890/forecast")
    assert r.status_code == 404


def test_forecast_insufficient_data_returns_null_delta(
    client: TestClient, db: Session
) -> None:
    db.add(_account(polled=True))
    db.flush()
    db.add(_snap("abcdefghij1234567890", days_ago=3, rating=2000))
    db.add(_snap("abcdefghij1234567890", days_ago=1, rating=2050))
    db.flush()
    r = client.get("/api/profile/abcdefghij1234567890/forecast?horizon=7")
    assert r.status_code == 200
    data = r.json()
    assert data["predicted_delta"] is None
    assert data["n_points"] == 2


def test_forecast_with_enough_data_returns_prediction(
    client: TestClient, db: Session
) -> None:
    db.add(_account(polled=True))
    db.flush()
    for i in range(10):
        db.add(_snap("abcdefghij1234567890", days_ago=10 - i, rating=2000 + i * 30))
    db.flush()
    r = client.get("/api/profile/abcdefghij1234567890/forecast?horizon=7&mode=overall")
    assert r.status_code == 200
    data = r.json()
    assert data["horizon"] == 7
    assert data["mode"] == "overall"
    assert isinstance(data["predicted_delta"], int)
    assert isinstance(data["predicted_rating"], int)
    assert isinstance(data["confidence"], int)
    assert data["n_points"] == 10


def test_forecast_invalid_mode_returns_422(client: TestClient, db: Session) -> None:
    db.add(_account(polled=True))
    db.flush()
    r = client.get("/api/profile/abcdefghij1234567890/forecast?mode=invalid")
    assert r.status_code == 422


def test_forecast_horizon_out_of_range_returns_422(
    client: TestClient, db: Session
) -> None:
    db.add(_account(polled=True))
    db.flush()
    r = client.get("/api/profile/abcdefghij1234567890/forecast?horizon=999")
    assert r.status_code == 422
