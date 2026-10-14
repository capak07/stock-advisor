from advisor.run import main


def clear_env(monkeypatch):
    for name in ("DATABASE_URL",):
        monkeypatch.delenv(name, raising=False)


def test_main_exits_quietly_outside_run_windows(monkeypatch, capsys):
    clear_env(monkeypatch)
    assert main(["--now", "2026-10-17T12:15:00+00:00"]) == 0  # Saturday
    assert "nothing to do" in capsys.readouterr().out


def test_main_fails_when_a_run_window_was_missed(monkeypatch, capsys):
    clear_env(monkeypatch)
    assert main(["--now", "2026-10-14T12:50:00+00:00"]) == 1  # 08:50 ET, 35 min late
    assert "missed" in capsys.readouterr().out
