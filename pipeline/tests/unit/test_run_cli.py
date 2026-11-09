from advisor.run import main


def clear_env(monkeypatch):
    for name in ("DATABASE_URL",):
        monkeypatch.delenv(name, raising=False)


def test_main_exits_quietly_outside_run_windows(monkeypatch, capsys):
    clear_env(monkeypatch)
    assert main(["--now", "2026-10-17T12:15:00+00:00"]) == 0  # Saturday
    assert "nothing to do" in capsys.readouterr().out


def test_main_fails_when_a_run_window_was_missed(monkeypatch, capsys):
    stub_db(monkeypatch, published=set())
    assert main(["--now", "2026-10-14T12:50:00+00:00"]) == 1  # 08:50 ET, 35 min late
    assert "pre_open run for 2026-10-14 never ran" in capsys.readouterr().out


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def stub_db(monkeypatch, published):
    """`published`: the (kind, et_date) pairs with a published run."""
    import advisor.run as run

    monkeypatch.setattr(run.Settings, "from_env", classmethod(lambda cls: type("S", (), {"database_url": "x"})()))
    monkeypatch.setattr(run, "connect", lambda url: _Conn())
    monkeypatch.setattr(run.repo, "has_published_run", lambda conn, kind, day: (kind.value, str(day)) in published)


def test_a_late_trigger_finding_a_slot_never_ran_fails_so_the_owner_hears(monkeypatch, capsys):
    # GitHub created the 12:15 UTC cron's run at 19:25 UTC on 11-06, 7 hours late
    stub_db(monkeypatch, published=set())
    assert main(["--now", "2026-11-06T19:25:00+00:00"]) == 1
    assert "pre_open run for 2026-11-06 never ran" in capsys.readouterr().out


def test_a_late_trigger_with_every_slot_already_run_exits_quietly(monkeypatch, capsys):
    stub_db(monkeypatch, published={("pre_open", "2026-11-06")})
    assert main(["--now", "2026-11-06T19:25:00+00:00"]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_an_in_window_trigger_runs_each_kind_once_per_et_date(monkeypatch, capsys):
    stub_db(monkeypatch, published={("pre_open", "2026-11-09")})
    assert main(["--now", "2026-11-09T13:15:00+00:00"]) == 0  # 08:15 EST, already published today
    assert "pre_open already published today" in capsys.readouterr().out
