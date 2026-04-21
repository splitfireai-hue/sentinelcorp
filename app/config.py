from __future__ import annotations

import logging
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./sentinelcorp.db"
    REDIS_URL: str = ""

    # App
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: str = ""
    API_TITLE: str = "SentinelCorp"
    API_VERSION: str = "0.1.0"

    # Free Tier
    FREE_TIER_ENABLED: bool = True
    FREE_TIER_REQUESTS: int = 1000

    # Rate Limiting
    LOOKUP_RATE_LIMIT: str = "60/minute"
    SEARCH_RATE_LIMIT: str = "30/minute"

    # Admin
    ADMIN_SECRET: str = ""

    # Third-party APIs (optional — use for MCA/GST data)
    SUREPASS_API_KEY: str = ""
    JAMKU_API_KEY: str = ""
    INDIAN_KANOON_API_KEY: str = ""

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def origins_list(self) -> List[str]:
        if not self.ALLOWED_ORIGINS:
            return ["*"] if not self.is_production else []
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "env_ignore_empty": True}


settings = Settings()


def setup_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
