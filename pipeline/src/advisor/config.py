"""Runtime settings loaded from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

REQUIRED = ("DATABASE_URL", "ALPACA_KEY_ID", "ALPACA_SECRET_KEY")


class ConfigError(RuntimeError):
    """Raised when required settings are missing."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    alpaca_key_id: str
    alpaca_secret_key: str
    cache_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        env = os.environ if env is None else env
        missing = [name for name in REQUIRED if not env.get(name)]
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            database_url=env["DATABASE_URL"],
            alpaca_key_id=env["ALPACA_KEY_ID"],
            alpaca_secret_key=env["ALPACA_SECRET_KEY"],
            cache_dir=Path(env.get("ADVISOR_CACHE_DIR", ".cache")),
        )
