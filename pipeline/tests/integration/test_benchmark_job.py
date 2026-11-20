from dataclasses import replace
from datetime import UTC, datetime, timedelta

from advisor.benchmark import job
from advisor.benchmark.accept import Decision, choose_model
from advisor.benchmark.policy_search import Tuned
from advisor.benchmark.report import render_markdown
from advisor.model.train import PARAMS, TrainConfig
from advisor.model.variants import BASELINE, ModelConfig
from advisor.models import Market
from advisor.policy import DEFAULT_POLICY
from advisor.store import repo
from model_data import write_group_histories, write_market

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


def test_a_first_benchmark_scores_the_baseline_and_accepts_it(db, tmp_path):
    write_market(tmp_path, Market.TSX, stocks=40)
    report = job.run(tmp_path, [Market.TSX], db, NOW, "abc1234", FAST)
    tsx = report["markets"]["TSX"]
    assert tsx["chosen"] == "baseline" and tsx["accepted"]["changed"] is True
    assert tsx["variants"]["ranker"]["status"] == "run"
    assert tsx["variants"]["garch+ranker+forest"]["status"] == "run"
    assert not set(tsx["variants"]) & {"factors", "extras", "ranker+extras", "ranker+extras+bagged"}  # retired
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
    assert "| ranker | run |" in text and "| garch+ranker+forest | run |" in text
    assert "Did the new data help?" not in text  # TSX runs no data group row
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
    factors = us["variants"]["factors+garch"]
    assert factors["status"] == "run"
    assert "alpha_rank_ic" in factors and "fallback_count" in factors
    assert isinstance(factors["french"], str) and factors["french"]
    text = render_markdown(report)
    assert "Factor diagnostic:" in text and "Kenneth French cross-check:" in text
    assert "nan" not in text and "None" not in text
    # no group history in this build: those rows fail closed as "no data" and the job carries on;
    # `earnings` needs only the SEC facts, so its row runs
    assert us["variants"]["garch+ranker+forest+short"] == {"status": "no data", "groups": ["short"]}
    assert "garch+ranker+forest+short" not in us["decisions"]
    assert us["variants"]["garch+ranker+forest+earnings"]["status"] == "run"
    assert "| garch+ranker+forest+short | no data: short | — | — | — | no data |" in text
    assert "| short | — | — | no data |" in text and "arrives with" not in text


def test_the_benchmark_scores_crypto(db, tmp_path):
    from advisor.model.crypto import CRYPTO
    from model_data import write_crypto
    write_crypto(tmp_path, coins=30, days=1300)
    report = job.run(tmp_path, [CRYPTO], db, NOW, None, FAST)
    assert report["markets"]["crypto"]["chosen"] == "baseline"
    folds = {r["fold"] for r in db.execute("select fold from benchmark_results where market = 'crypto' and variant = 'baseline'").fetchall()}
    assert folds == {"0", "1", "2", "3", "pooled"}
    assert repo.active_config(db, "crypto").reason == "first benchmark: today's model"


def test_the_combined_row_runs_when_two_groups_pass(db, tmp_path, monkeypatch):
    stocks = write_market(tmp_path, Market.US, stocks=40, days=1200)
    write_group_histories(tmp_path, stocks)
    base = ModelConfig(ranker=True, garch=True, forest=True)
    rows = {
        "baseline": BASELINE, "garch+ranker+forest": base,
        "garch+ranker+forest+short": replace(base, short=True),
        "garch+ranker+forest+estimates": replace(base, estimates=True),
        "full+policy": None,
    }
    monkeypatch.setattr(job, "ABLATIONS", rows)
    monkeypatch.setattr(job, "BASE_ROWS", job.base_rows(rows))
    combined = "garch+ranker+forest+short+estimates"
    calls = []

    def pass_them(baseline, candidates, incumbent, twins=None):
        calls.append((set(candidates), incumbent, dict(twins or {})))
        decisions = {name: Decision(True, (f"{name} passed",)) for name in candidates}
        return (combined if combined in candidates else "baseline"), decisions

    monkeypatch.setattr(job, "choose_model", pass_them)
    monkeypatch.setattr(job, "tune_for_outer", lambda *a, **k: Tuned(None, None, 0, "no stage-1 combination met the limits: x"))
    report = job.run(tmp_path, [Market.US], db, NOW, None, FAST)
    us = report["markets"]["US"]
    assert "error" not in us, us.get("error")
    assert [call[0] for call in calls] == [set(rows) - {"baseline", "full+policy"}, set(rows) - {"baseline", "full+policy"} | {combined}]
    assert calls[1][2][combined] == "garch+ranker+forest"  # it must beat the base row too
    assert us["variants"][combined]["status"] == "run" and us["combined"] == combined
    assert us["chosen"] == combined and us["variants"]["full+policy"]["model"] == combined
    expected = replace(base, short=True, estimates=True).to_json()
    assert repo.active_config(db, "US").config == expected and us["accepted"]["config"] == expected
    variants = {r["variant"] for r in db.execute("select distinct variant from benchmark_results").fetchall()}
    assert combined in variants
    table = render_markdown(report).split("### Did the new data help?", 1)[1].split("### Ablations", 1)[0]
    assert table.strip().splitlines()[-1].startswith(f"| {combined} | ")


def test_an_active_config_without_a_row_is_still_scored(db, tmp_path, monkeypatch):
    # a retired row (or last month's combined row) stays accepted until something beats it
    write_market(tmp_path, Market.TSX, stocks=40)
    monkeypatch.setattr(job, "ABLATIONS", {"baseline": BASELINE, "full+policy": None})
    monkeypatch.setattr(job, "BASE_ROWS", {})
    monkeypatch.setattr(job, "tune_for_outer", lambda *a, **k: Tuned(None, None, 0, "no stage-1 combination met the limits: x"))
    retired = ModelConfig(ranker=True, extras=True)
    run_id = repo.start_benchmark_run(db, NOW, None)
    first = repo.accept_config(db, "TSX", retired.to_json(), "test", run_id, NOW)
    seen = []

    def keep_it(baseline, candidates, incumbent, twins=None):
        seen.append(incumbent)
        _, decisions = choose_model(baseline, candidates, incumbent, twins)
        return "ranker+extras", decisions

    monkeypatch.setattr(job, "choose_model", keep_it)
    report = job.run(tmp_path, [Market.TSX], db, NOW + timedelta(days=28), None, FAST)
    tsx = report["markets"]["TSX"]
    assert "error" not in tsx, tsx.get("error")
    assert tsx["variants"]["ranker+extras"]["status"] == "run"
    assert [name for name, _ in seen] == ["ranker+extras"]  # scored, and judged as the incumbent
    assert "ranker+extras" in tsx["decisions"]
    assert tsx["chosen"] == "ranker+extras" and tsx["accepted"]["changed"] is False
    assert repo.active_config(db, "TSX").id == first
