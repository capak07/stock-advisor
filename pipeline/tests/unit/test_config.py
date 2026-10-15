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


def test_the_sec_contact_is_optional_and_blank_means_unset():
    assert Settings.from_env({"DATABASE_URL": "x"}).sec_user_agent is None
    assert Settings.from_env({"DATABASE_URL": "x", "SEC_USER_AGENT": ""}).sec_user_agent is None
    contact = "stock-advisor you@example.com"
    assert Settings.from_env({"DATABASE_URL": "x", "SEC_USER_AGENT": contact}).sec_user_agent == contact


def test_repr_hides_the_sec_contact():
    settings = Settings.from_env({"DATABASE_URL": "x", "SEC_USER_AGENT": "dev you@example.com"})
    assert "you@example.com" not in repr(settings)
