from pathlib import Path

import pytest

from advisor.config import ConfigError, Settings

FULL = {
    "DATABASE_URL": "postgresql://u:p@h/db",
    "ALPACA_KEY_ID": "k",
    "ALPACA_SECRET_KEY": "s",
}


def test_from_env_reads_required_values_and_default_cache_dir():
    settings = Settings.from_env(FULL)
    assert settings.database_url == "postgresql://u:p@h/db"
    assert settings.alpaca_key_id == "k"
    assert settings.alpaca_secret_key == "s"
    assert settings.cache_dir == Path(".cache")


def test_from_env_honours_cache_dir_override():
    settings = Settings.from_env({**FULL, "ADVISOR_CACHE_DIR": "/tmp/advisor"})
    assert settings.cache_dir == Path("/tmp/advisor")


def test_from_env_lists_every_missing_variable():
    with pytest.raises(ConfigError, match="ALPACA_KEY_ID, ALPACA_SECRET_KEY"):
        Settings.from_env({"DATABASE_URL": "x"})


def test_repr_hides_database_url_and_alpaca_secret():
    settings = Settings.from_env({
        "DATABASE_URL": "postgresql://u:db-password-123@h/db",
        "ALPACA_KEY_ID": "k",
        "ALPACA_SECRET_KEY": "alpaca-secret-456",
    })
    text = repr(settings)
    assert "db-password-123" not in text
    assert "alpaca-secret-456" not in text
