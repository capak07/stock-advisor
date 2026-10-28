from dataclasses import replace
from datetime import UTC, datetime, timedelta

from advisor.benchmark import job
from advisor.benchmark.report import render_markdown
from advisor.model.train import PARAMS, TrainConfig
from advisor.model.variants import BASELINE
from advisor.models import Market
from advisor.store import repo
from model_data import write_market

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_a_first_benchmark_scores_the_baseline_and_accepts_it(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = job.run(tmp_path, [Market.TSX], db, NOW, "abc1234", FAST)
    tsx = report["markets"]["TSX"]
    assert tsx["chosen"] == "baseline" and tsx["accepted"]["changed"] is True
    assert tsx["variants"]["factors"] == {"status": "not built", "plan": "Plan 6c"}
    assert tsx["variants"]["full+policy"] == {"status": "not built", "plan": "Plan 6e"}
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
    assert "| baseline | run |" in text and "| garch | arrives with Plan 6d |" in text
    assert "nan" not in text and "None" not in text


def test_a_second_benchmark_keeps_the_accepted_config(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    job.run(tmp_path, [Market.TSX], db, NOW, None, FAST)
    first = repo.active_config(db, "TSX").id
    report = job.run(tmp_path, [Market.TSX], db, NOW + timedelta(days=28), None, FAST)
    assert report["markets"]["TSX"]["accepted"]["changed"] is False
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
