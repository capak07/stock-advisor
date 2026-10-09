from advisor.run import main


def test_main_exits_quietly_outside_run_windows(monkeypatch, capsys):
    for name in ("DATABASE_URL", "ALPACA_KEY_ID", "ALPACA_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--now", "2026-10-17T12:15:00+00:00"]) == 0  # Saturday
    assert "nothing to do" in capsys.readouterr().out
