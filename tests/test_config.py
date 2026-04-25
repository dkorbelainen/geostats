from geostats.config import Settings


def test_settings_loads_required_fields(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    s = Settings()
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert s.poll_interval_hours == 6
    assert s.poll_batch_size == 50
    assert s.poll_request_delay_sec == 1.5
    assert s.geoguessr_ncfa_cookie is None
    assert s.raw_response_logging is False


def test_settings_accepts_optional_cookie(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("GEOGUESSR_NCFA_COOKIE", "abc")
    assert Settings().geoguessr_ncfa_cookie == "abc"
