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
    acc = db.get(Account, "abcdefghij1234567890")
    assert acc is not None
    assert acc.nick == "RealNick"
    assert r.headers["location"] == f"/profile/{acc.slug or 'abcdefghij1234567890'}"


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


# ── anomaly card ──────────────────────────────────────────────────────────────

def test_profile_renders_anomaly_card(client, db) -> None:
    from datetime import UTC, datetime
    from geostats.models import Account, AccountAnomaly, RatingSnapshot

    now = datetime.now(UTC)
    db.add(Account(id="anomA", nick="anomA", slug="anoma", created_at=now,
                   last_polled_at=now))
    db.add(RatingSnapshot(
        account_id="anomA", captured_at=now, rating=2500,
        division_number=None, division_name=None,
        rating_moving=None, rating_nomove=None, rating_nmpz=None,
        win_streak=10, guessed_first_rate=0.7,
        games_played=300, games_won=210, avg_guess_distance_km=80.0,
        position_overall=None, position_moving=None, position_nomove=None,
        position_nmpz=None, position_country=None,
    ))
    db.add(AccountAnomaly(
        account_id="anomA", score=-0.2, confidence_pct=85,
        driver_1_feature="peak_win_streak", driver_1_z=3.4,
        driver_2_feature="mean_avg_guess_distance_km", driver_2_z=-2.1,
        computed_at=now,
    ))
    db.commit()

    resp = client.get("/profile/anoma")
    assert resp.status_code == 200
    body = resp.text
    assert "Profile rarity" in body
    assert "85%" in body
    assert "Peak win streak" in body
    assert "Average distance" in body


def test_profile_hides_anomaly_card_below_threshold(client, db) -> None:
    from datetime import UTC, datetime
    from geostats.models import Account, AccountAnomaly, RatingSnapshot

    now = datetime.now(UTC)
    db.add(Account(id="quietA", nick="quietA", slug="quieta", created_at=now,
                   last_polled_at=now))
    db.add(RatingSnapshot(
        account_id="quietA", captured_at=now, rating=1500,
        division_number=None, division_name=None,
        rating_moving=None, rating_nomove=None, rating_nmpz=None,
        win_streak=2, guessed_first_rate=0.4,
        games_played=200, games_won=100, avg_guess_distance_km=400.0,
        position_overall=None, position_moving=None, position_nomove=None,
        position_nmpz=None, position_country=None,
    ))
    db.add(AccountAnomaly(
        account_id="quietA", score=0.05, confidence_pct=42,
        driver_1_feature="mean_rating", driver_1_z=0.4,
        driver_2_feature=None, driver_2_z=None,
        computed_at=now,
    ))
    db.commit()

    resp = client.get("/profile/quieta")
    assert resp.status_code == 200
    assert "Profile rarity" not in resp.text


# ── /leaderboard ──────────────────────────────────────────────────────────────

def _tracked_account(db: Session, id: str, nick: str, rating: int) -> None:
    acc = Account(
        id=id,
        nick=nick,
        created_at=_now(),
        last_polled_at=_now(),
        tracked=True,
    )
    db.add(acc)
    db.flush()
    db.add(RatingSnapshot(
        account_id=id,
        captured_at=_now(),
        rating=rating,
        position_overall=None,
    ))
    db.flush()


def test_leaderboard_default_mode(client: TestClient) -> None:
    r = client.get("/leaderboard")
    assert r.status_code == 200
    assert "Overall" in r.text


def test_leaderboard_shows_tracked_players(client: TestClient, db: Session) -> None:
    _tracked_account(db, "aaaaaaaaaa1234567890", "AlphaPlayer", 3000)
    r = client.get("/leaderboard")
    assert r.status_code == 200
    assert "AlphaPlayer" in r.text


def test_leaderboard_limit_25_restricts_rows(client: TestClient, db: Session) -> None:
    for i in range(30):
        uid = f"user{i:016d}"
        _tracked_account(db, uid, f"Player{i}", 3000 - i)
    r = client.get("/leaderboard?limit=25")
    assert r.status_code == 200
    assert r.text.count('<a class="lb-row') <= 25


def test_leaderboard_invalid_limit_defaults_to_100(client: TestClient) -> None:
    r = client.get("/leaderboard?limit=999")
    assert r.status_code == 200
    assert "Top 100" in r.text


def test_leaderboard_limit_in_response(client: TestClient) -> None:
    r = client.get("/leaderboard?limit=250")
    assert r.status_code == 200
    assert "Top 250" in r.text


# ── /api/search ───────────────────────────────────────────────────────────────

def test_search_returns_empty_for_short_query(client: TestClient) -> None:
    r = client.get("/api/search?q=a")
    assert r.status_code == 200
    assert r.json() == []


def test_search_finds_by_nick(client: TestClient, db: Session) -> None:
    acc = Account(
        id="searchtest1234567890",
        nick="UniqueNick",
        created_at=_now(),
        last_polled_at=_now(),
    )
    db.add(acc)
    db.flush()
    db.add(RatingSnapshot(
        account_id="searchtest1234567890",
        captured_at=_now(),
        rating=2500,
        position_overall=42,
        position_moving=38,
        position_nomove=None,
        position_nmpz=None,
    ))
    db.flush()
    r = client.get("/api/search?q=Unique")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["nick"] == "UniqueNick"
    assert data[0]["rating"] == 2500
    assert data[0]["position_overall"] == 42
    assert data[0]["position_moving"] == 38
    assert data[0]["position_nomove"] is None
    assert data[0]["position_nmpz"] is None


def test_search_no_results(client: TestClient) -> None:
    r = client.get("/api/search?q=zzznomatch")
    assert r.status_code == 200
    assert r.json() == []


def test_search_sorts_by_rating_desc(client: TestClient, db: Session) -> None:
    accounts = [
        ("sortacc1aaaaaaaaaaaa", "panLOW", 645),
        ("sortacc2bbbbbbbbbbbb", "panTOP", 1932),
        ("sortacc3cccccccccccc", "panMID", 1523),
        ("sortacc4dddddddddddd", "panBOT", 834),
    ]
    for acc_id, nick, rating in accounts:
        db.add(Account(id=acc_id, nick=nick, created_at=_now(), last_polled_at=_now()))
        db.flush()
        db.add(RatingSnapshot(account_id=acc_id, captured_at=_now(), rating=rating))
    db.flush()
    r = client.get("/api/search?q=pan&mode=overall")
    assert r.status_code == 200
    data = r.json()
    ratings = [row["rating"] for row in data]
    assert ratings == sorted(ratings, reverse=True), ratings
