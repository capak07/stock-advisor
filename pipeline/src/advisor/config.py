"""Runtime settings loaded from environment variables. No data source needs a key (spec R7)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

REQUIRED = ("DATABASE_URL",)


class ConfigError(RuntimeError):
    """Raised when required settings are missing."""


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)  # holds the database password
    cache_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        env = os.environ if env is None else env
        missing = [name for name in REQUIRED if not env.get(name)]
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            database_url=env["DATABASE_URL"],
            cache_dir=Path(env.get("ADVISOR_CACHE_DIR", ".cache")),
        )
