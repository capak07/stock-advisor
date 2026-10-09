import pytest
from psycopg.conninfo import conninfo_to_dict


def require_test_database(url: str) -> None:
    """Fail the test unless the URL names a *_test database (the db fixture drops schemas)."""
    dbname = conninfo_to_dict(url).get("dbname") or ""
    if not dbname.endswith("_test"):
        pytest.fail(
            f"refusing to reset non-test database {dbname!r}: "
            "TEST_DATABASE_URL must name a *_test database"
        )
