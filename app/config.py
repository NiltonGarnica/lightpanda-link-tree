from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    lightpanda_ws_url: str = "ws://localhost:9222/"
    lightpanda_http_url: str = "http://localhost:9222"
    max_links: int = 500
    max_concurrency: int = 4
    page_timeout_seconds: float = 15
    crawl_timeout_seconds: float = 120
    tree_cache_size: int = 100
    allow_private_networks: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
