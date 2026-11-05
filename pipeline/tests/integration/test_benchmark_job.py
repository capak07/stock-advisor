from dataclasses import replace
from datetime import UTC, datetime, timedelta

from advisor.benchmark import job
from advisor.benchmark.accept import Decision
from advisor.benchmark.policy_search import Tuned
from advisor.benchmark.report import render_markdown
from advisor.model.train import PARAMS, TrainConfig
from advisor.model.variants import BASELINE, ModelConfig
from advisor.models import Market
from advisor.policy import DEFAULT_POLICY
from advisor.store import repo
from model_data import write_market

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_a_first_benchmark_scores_the_baseline_and_accepts_it(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = job.run(tmp_path, [Market.TSX], db, NOW, "abc1234", FAST)
    tsx = report["markets"]["TSX"]
    assert tsx["chosen"] == "baseline" and tsx["accepted"]["changed"] is True
    assert tsx["variants"]["factors"]["status"] == "run"
    assert tsx["variants"]["ranker"]["status"] == "run"
    assert tsx["variants"]["ranker+extras+bagged"]["status"] == "run"
    assert tsx["variants"]["garch"]["status"] == "run" and tsx["variants"]["factors+garch"]["status"] == "run"
    assert tsx["variants"]["garch"]["garch"]["fallbacks"] >= 0
    assert tsx["variants"]["full+policy"]["status"] == "run"
    assert tsx["variants"]["baseline"]["status"] == "run"
    folds = {r["fold"] for r in db.execute("select fold from benchmark_results where variant = 'baseline'").fetchall()}
    assert folds == {"0", "1", "2", "3", "pooled"}
    run = db.execute("select * from benchmark_runs").fetchone()
    assert (run["status"], run["git_sha"]) == ("success", "abc1234")
    assert run["report"]["markets"]["TSX"]["chosen"] == "baseline"
    active = repo.active_config(db, "TSX")
    assert active.config == BASELINE.to_json() and active.reason == "first benchmark: today's model"
    assert active.benchmark_run_id == run["id"]
    text = render_markdown(report)  # the real report renders, with nothing unmeasured shown as nan
    assert "| baseline | run |" in text and "| garch | run |" in text and "GARCH: " in text
    assert "| ranker | run |" in text and "| ranker+extras+bagged | run |" in text
    policy_folds = {r["fold"] for r in db.execute("select fold from benchmark_results where variant = 'full+policy'").fetchall()}
    assert policy_folds == {"1", "2", "3", "pooled"}
    assert {"default", "candidate"} <= set(tsx["variants"]["full+policy"]["policy"])
    assert "nan" not in text and "None" not in text


def test_a_second_benchmark_keeps_the_accepted_config(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    job.run(tmp_path, [Market.TSX], db, NOW, None, FAST)
    first = repo.active_config(db, "TSX").id
    report = job.run(tmp_path, [Market.TSX], db, NOW + timedelta(days=28), None, FAST)
    assert report["markets"]["TSX"]["accepted"]["changed"] is False
    assert repo.active_config(db, "TSX").id == first
    assert db.execute("select count(*) as n from accepted_configs").fetchone()["n"] == 1


def test_a_kept_version_1_config_is_unchanged(db, tmp_path, monkeypatch):
    # configs accepted before Plan 6f are stored as version 1; keeping one is not a change
    write_market(tmp_path, Market.TSX, stocks=40)
    monkeypatch.setattr(job, "ABLATIONS", {"baseline": BASELINE, "full+policy": None})
    run_id = repo.start_benchmark_run(db, NOW, None)
    v1 = {"version": 1, "factors": False, "garch": False, "policy": None}
    first = repo.accept_config(db, "TSX", v1, "test", run_id, NOW)
    report = job.run(tmp_path, [Market.TSX], db, NOW + timedelta(days=28), None, FAST)
    tsx = report["markets"]["TSX"]
    assert tsx["chosen"] == "baseline" and tsx["accepted"]["changed"] is False
    assert repo.active_config(db, "TSX").id == first
    assert db.execute("select count(*) as n from accepted_configs").fetchone()["n"] == 1


def test_a_kept_version_2_config_is_unchanged(db, tmp_path, monkeypatch):
    # configs accepted under Plan 6f are stored as version 2; choosing one again is not a change
    write_market(tmp_path, Market.TSX, stocks=40)
    monkeypatch.setattr(job, "ABLATIONS", {"baseline": BASELINE, "ranker": ModelConfig(ranker=True), "full+policy": None})
    monkeypatch.setattr(job, "choose_model", lambda *a, **k: ("ranker", {}))
    monkeypatch.setattr(
        job, "tune_for_outer", lambda *a, **k: Tuned(None, None, 0, "no stage-1 combination met the limits: x")
    )
    run_id = repo.start_benchmark_run(db, NOW, None)
    v2 = {"version": 2, "factors": False, "garch": False, "ranker": True, "policy": None}
    first = repo.accept_config(db, "TSX", v2, "test", run_id, NOW)
    report = job.run(tmp_path, [Market.TSX], db, NOW + timedelta(days=28), None, FAST)
    tsx = report["markets"]["TSX"]
    assert tsx["chosen"] == "ranker" and tsx["accepted"]["changed"] is False
    assert repo.active_config(db, "TSX").id == first
    assert db.execute("select count(*) as n from accepted_configs").fetchone()["n"] == 1


def test_a_failed_market_changes_nothing_and_fails_the_run(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)  # no US files
    report = job.run(tmp_path, [Market.US, Market.TSX], db, NOW, None, FAST)
    assert report["markets"]["US"]["error"].startswith("FileNotFoundError")
    assert "chosen" in report["markets"]["TSX"] and job.exit_code(report) == 1
    assert db.execute("select status from benchmark_runs").fetchone()["status"] == "failed"
    assert repo.active_config(db, "US") is None


def test_a_variant_that_scores_different_rows_is_never_compared(db, tmp_path, monkeypatch):
    write_market(tmp_path, Market.TSX, stocks=40)
    real = job.run_variant

    def fewer_rows(data, config, *args, **kwargs):
        wf = real(data, BASELINE, *args, **kwargs)
        return wf if config == BASELINE else replace(wf, predictions=wf.predictions.iloc[1:])

    monkeypatch.setattr(job, "run_variant", fewer_rows)
    monkeypatch.setattr(job, "unbuilt", lambda config: None)  # pretend factors is built
    report = job.run(tmp_path, [Market.TSX], db, NOW, None, FAST)
    assert "scored different rows than the baseline" in report["markets"]["TSX"]["error"]
    assert repo.active_config(db, "TSX") is None


def test_the_pipeline_role_can_record_a_benchmark(db):
    db.execute("set role pipeline_rw")
    try:
        run_id = repo.start_benchmark_run(db, NOW, None)
        repo.accept_config(db, "TSX", BASELINE.to_json(), "test", run_id, NOW)
        repo.finish_benchmark_run(db, run_id, NOW, "success", {})
        assert repo.active_config(db, "TSX").benchmark_run_id == run_id
    finally:
        db.execute("reset role")


def test_a_policy_that_fails_keeps_the_model_without_one(db, tmp_path, monkeypatch):
    write_market(tmp_path, Market.TSX, stocks=40)
    monkeypatch.setattr(job, "tune_for_outer", lambda *a, **k: Tuned(None, None, 0, "no stage-1 combination met the limits: x"))
    report = job.run(tmp_path, [Market.TSX], db, NOW, None, FAST)
    assert repo.active_config(db, "TSX").config["policy"] is None
    assert "no stage-1 combination met the limits: x" in report["markets"]["TSX"]["decisions"]["full+policy"]["reasons"][0]


def test_an_accepted_policy_is_stored_with_the_model(db, tmp_path, monkeypatch):
    write_market(tmp_path, Market.TSX, stocks=40)
    tuned = replace(DEFAULT_POLICY, p_buy=0.54, rule="p")
    monkeypatch.setattr(job, "tune_for_outer", lambda *a, **k: Tuned(tuned, 1.0, 127, "ok"))
    monkeypatch.setattr(job, "accept_policy", lambda c, d: Decision(True, ("net Sharpe 1.00 vs 0.00 for today's rules, 40 trades",)))
    report = job.run(tmp_path, [Market.TSX], db, NOW, None, FAST)
    active = repo.active_config(db, "TSX")
    assert active.config["policy"] == tuned.to_json() and report["markets"]["TSX"]["accepted"]["changed"] is True
    assert active.reason.startswith("net Sharpe 1.00")
    again = job.run(tmp_path, [Market.TSX], db, NOW + timedelta(days=28), None, FAST)
    assert again["markets"]["TSX"]["accepted"]["changed"] is False


def test_the_factors_variant_runs_on_us_data_and_keeps_the_baseline_rows(db, tmp_path):
    write_market(tmp_path, Market.US, stocks=40, days=1200)
    report = job.run(tmp_path, [Market.US], db, NOW, None, FAST)
    us = report["markets"]["US"]
    assert "error" not in us
    factors = us["variants"]["factors"]
    assert factors["status"] == "run"
    assert "alpha_rank_ic" in factors and "fallback_count" in factors
    assert isinstance(factors["french"], str) and factors["french"]
    text = render_markdown(report)
    assert "Factor diagnostic:" in text and "Kenneth French cross-check:" in text
    assert "nan" not in text and "None" not in text


def test_the_benchmark_scores_crypto(db, tmp_path):
    from advisor.model.crypto import CRYPTO
    from model_data import write_crypto
    write_crypto(tmp_path, coins=30, days=1300)
    report = job.run(tmp_path, [CRYPTO], db, NOW, None, FAST)
    assert report["markets"]["crypto"]["chosen"] == "baseline"
    folds = {r["fold"] for r in db.execute("select fold from benchmark_results where market = 'crypto' and variant = 'baseline'").fetchall()}
    assert folds == {"0", "1", "2", "3", "pooled"}
    assert repo.active_config(db, "crypto").reason == "first benchmark: today's model"
