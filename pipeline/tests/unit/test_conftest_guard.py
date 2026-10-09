import pytest

from dbguard import require_test_database


def test_refuses_non_test_database():
    with pytest.raises(pytest.fail.Exception, match="refusing to reset"):
        require_test_database("postgresql://u:p@db.example.supabase.co:5432/postgres")


def test_refuses_key_value_form_and_missing_dbname():
    with pytest.raises(pytest.fail.Exception):
        require_test_database("host=db.example.supabase.co dbname=postgres user=u")
    with pytest.raises(pytest.fail.Exception):
        require_test_database("postgresql://u:p@localhost:5432")


def test_accepts_test_database():
    require_test_database("postgresql://postgres:postgres@localhost:54329/advisor_test")
    require_test_database("host=localhost dbname=advisor_test user=postgres")
