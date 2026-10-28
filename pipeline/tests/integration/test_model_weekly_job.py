from datetime import UTC, datetime, timedelta

from advisor.model import weekly
from advisor.model.train import PARAMS, TrainConfig, from_files
from advisor.model.variants import BASELINE
from advisor.models import Market
from advisor.store import repo
from model_data import write_market

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_the_weekly_job_trains_promotes_and_stores_a_market(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["promoted"] is True and report["TSX"]["reason"] == "first model"
    active = repo.active_model(db, "stock_tsx")
    assert active.version == "stock_tsx-202610241000"
    assert active.metrics["mean_rank_ic"] > 0.05
    assert {"horizons", "backtest", "picks_enabled", "picks_reason", "rows", "features"} <= set(active.metrics)
    assert active.calibration_error <= 5
    assert report["TSX"]["usable_horizons"] == [5, 63]
    # where the backtest's forecasts drop out of the pick rules, so "0 picks" can be read
    assert {"forecasts", "p_at_least_floor", "above_cost", "both", "p_max"} <= set(report["TSX"]["funnel"])
    assert active.metrics["backtest"]["funnel"] == report["TSX"]["funnel"]
    assert active.metrics["usable_horizons"] == [5, 63]
    model = from_files(repo.load_model_files(db, active.version))
    assert model.horizons == (5, 63)


def test_a_worse_model_is_stored_but_the_active_one_stays(db, tmp_path):
    good, noise = tmp_path / "good", tmp_path / "noise"
    write_market(good, Market.TSX, stocks=40)
    write_market(noise, Market.TSX, stocks=40, signal=0.0, seed=8)
    weekly.run(good, [Market.TSX], db, NOW, FAST)
    report = weekly.run(noise, [Market.TSX], db, NOW + timedelta(days=7), FAST)
    assert report["TSX"]["promoted"] is False
    assert repo.active_model(db, "stock_tsx").version == "stock_tsx-202610241000"
    assert db.execute("select count(*) as n from models").fetchone()["n"] == 2


def test_a_market_that_fails_to_train_is_reported_and_the_rest_carry_on(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)  # no US files
    report = weekly.run(tmp_path, [Market.US, Market.TSX], db, NOW, FAST)
    assert report["US"]["error"].startswith("FileNotFoundError")
    assert report["TSX"]["promoted"] is True
    assert weekly.exit_code(report) == 1
    assert repo.active_model(db, "stock_us") is None


def _accept(db, market, config):
    run_id = repo.start_benchmark_run(db, NOW, None)
    return repo.accept_config(db, market, config, "test", run_id, NOW)


def test_weekly_training_uses_the_baseline_until_a_config_is_accepted(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["config"] == "baseline"
    assert report["TSX"]["config_reason"] == "no accepted configuration yet: baseline"
    assert repo.active_model(db, "stock_tsx").metrics["config"] == BASELINE.to_json()


def test_weekly_training_follows_the_accepted_config(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    config_id = _accept(db, "TSX", BASELINE.to_json())
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["config_reason"] == f"accepted configuration #{config_id} (baseline)"


def test_a_config_this_code_cannot_run_falls_back_to_the_baseline(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    config_id = _accept(db, "TSX", {"version": 1, "factors": True, "garch": False, "policy": None})
    report = weekly.run(tmp_path, [Market.TSX], db, NOW, FAST)
    assert report["TSX"]["config"] == "baseline" and report["TSX"]["promoted"] is True
    assert report["TSX"]["config_reason"].startswith(f"accepted configuration #{config_id} can't be used (")
    assert "Plan 6c" in report["TSX"]["config_reason"]
