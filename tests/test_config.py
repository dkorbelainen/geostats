from geostats.config import Settings, get_settings


def test_settings_loads_required_fields(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    s = Settings()
    defaults = Settings.model_fields
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert s.poll_interval_hours == defaults["poll_interval_hours"].default
    assert s.poll_batch_size == defaults["poll_batch_size"].default
    assert s.poll_request_delay_sec == defaults["poll_request_delay_sec"].default
    assert s.geoguessr_ncfa_cookie is None
    assert s.raw_response_logging is False


def test_settings_accepts_optional_cookie(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("GEOGUESSR_NCFA_COOKIE", "abc")
    assert Settings().geoguessr_ncfa_cookie == "abc"


def test_get_settings_returns_cached_instance(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()
