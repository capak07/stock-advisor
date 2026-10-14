from pathlib import Path

import pytest

from advisor.config import ConfigError, Settings


def test_from_env_reads_the_database_url_and_default_cache_dir():
    settings = Settings.from_env({"DATABASE_URL": "postgresql://u:p@h/db"})
    assert settings.database_url == "postgresql://u:p@h/db"
    assert settings.cache_dir == Path(".cache")


def test_from_env_honours_cache_dir_override():
    settings = Settings.from_env({"DATABASE_URL": "x", "ADVISOR_CACHE_DIR": "/tmp/advisor"})
    assert settings.cache_dir == Path("/tmp/advisor")


def test_from_env_requires_only_the_database_url():  # spec R7: no data source needs a key
    with pytest.raises(ConfigError, match="Missing required environment variables: DATABASE_URL$"):
        Settings.from_env({})


def test_repr_hides_the_database_url():
    settings = Settings.from_env({"DATABASE_URL": "postgresql://u:db-password-123@h/db"})
    assert "db-password-123" not in repr(settings)
