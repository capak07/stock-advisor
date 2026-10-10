from advisor.store.migrate import main


def test_cli_requires_admin_database_url(monkeypatch, capsys):
    monkeypatch.delenv("ADMIN_DATABASE_URL", raising=False)
    assert main([]) == 2
    assert "ADMIN_DATABASE_URL" in capsys.readouterr().err
