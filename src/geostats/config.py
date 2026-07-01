from datetime import UTC, datetime
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    geoguessr_ncfa_cookie: str | None = None
    poll_batch_size: int = 50
    poll_request_delay_sec: float = 3.0
    raw_response_logging: bool = False
    rating_system_cutoff: datetime = datetime(2026, 7, 1, tzinfo=UTC)


@lru_cache
def get_settings() -> Settings:
    return Settings()
