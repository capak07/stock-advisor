"""The monthly benchmark: score every built ablation per market, and accept a configuration.

Run as `python -m advisor.benchmark.job --data DIR --out DIR` after the training data is built.
Each variant runs on the same outer folds as the baseline and is judged only on them. The run,
every fold's scores and the report are stored; a market's accepted configuration changes only
when the evidence says so. A market that fails is reported, keeps its accepted configuration,
and the rest carry on.
"""

import argparse
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from advisor.benchmark.accept import (
    MIN_FOLDS_IMPROVED,
    PINBALL_TOLERANCE,
    Decision,
    Scores,
    accept_policy,
    choose_model,
)
from advisor.benchmark.folds import INNER_MIN_TRAIN_YEARS, INNER_SPLITS
from advisor.benchmark.metrics import calibrated_horizons, model_metrics, policy_metrics, summary
from advisor.benchmark.policy_search import score, score_each, tune_for_outer
from advisor.benchmark.report import render_markdown, write_reports
from advisor.benchmark.simulate import DailyPanel, daily_panel
from advisor.config import Settings
from advisor.model.backtest import MAX_CALIBRATION_PTS
from advisor.model.crypto import CRYPTO, CRYPTO_HORIZONS, load_crypto
from advisor.model.dataset import SAMPLE_EVERY, MarketData, load_market
from advisor.model.factors import french_cross_check
from advisor.model.train import Fold, TrainConfig, WalkForward
from advisor.model.variants import BASELINE, ModelConfig, run_variant, unbuilt
from advisor.model.weekly import crypto_skipped, json_safe
from advisor.models import BenchmarkResult, Market
from advisor.policy import DEFAULT_POLICY, Policy
from advisor.store import repo
from advisor.store.db import connect

# The design's five ablation rows. The last is the chosen model plus a policy tuned for it.
ABLATIONS: dict[str, ModelConfig | None] = {
    "baseline": BASELINE,
    "factors": ModelConfig(factors=True),
    "garch": ModelConfig(garch=True),
    "factors+garch": ModelConfig(factors=True, garch=True),
    "full+policy": None,
}
POLICY_ROW = "full+policy"
FIRST = "first benchmark: today's model"
MARKET_ORDER = [Market.TSX, Market.US, CRYPTO]  # the smaller load first, as in the weekly job


def _keys(predictions: pd.DataFrame) -> pd.DataFrame:
    return predictions[["day", "symbol", "horizon"]].sort_values(["day", "symbol", "horizon"]).reset_index(drop=True)


def _model_name(stored: Mapping[str, Any]) -> str | None:
    """The stored config's model part ("baseline", "factors", ...), without its policy."""
    try:
        return replace(ModelConfig.from_json(stored), policy=None).name
    except ValueError:
        return None


def _policy_row(
    data: MarketData,
    model: ModelConfig,
    wf: WalkForward,
    usable: Sequence[int],
    panel: DailyPanel,
    market: Market,
    fee: float,
    config: TrainConfig,
) -> tuple[dict, Decision, Policy | None, str]:
    """Tune a policy inside each outer fold 1-3, score it on that fold against today's rules, and,
    if it passes, re-tune once over the whole history: the policy that would go live."""
    pred = wf.predictions
    pred = pred[pred["p"].notna() & pred["horizon"].isin(usable)]
    periods = list(wf.folds[1:])  # fold 0 has no calibrated P, so no policy score
    default = score(pred, panel, DEFAULT_POLICY, market, fee, periods)
    tuned = [tune_for_outer(data, model, config, panel, market, fee, outer) for outer in periods]
    report = {
        "default": default, "candidate": None, "final": None, "final_reason": None,
        "per_fold": [t.policy.to_json() if t.policy else None for t in tuned],
        "per_fold_reasons": [t.reason for t in tuned],
    }
    missing = next(((k, t) for k, t in enumerate(tuned, start=1) if t.policy is None), None)
    if missing is not None:
        return report, Decision(False, (f"outer fold {missing[0]}: {missing[1].reason}",)), None, ""
    candidate = score_each(pred, panel, [t.policy for t in tuned], market, fee, periods)
    report["candidate"] = candidate
    decision = accept_policy(candidate, default)
    if not decision.accepted:
        return report, decision, None, ""
    last = pd.Timestamp(data.rows["day"].max())
    whole = Fold(last + timedelta(days=1), last + timedelta(days=2))
    final = tune_for_outer(data, model, config, panel, market, fee, whole)
    report["final"] = final.policy.to_json() if final.policy else None
    report["final_reason"] = final.reason
    return report, decision, final.policy, final.reason


def _benchmark_market(
    data_dir: Path, market: Market | str, conn: psycopg.Connection, run_id: int, now: datetime, config: TrainConfig
) -> dict:
    coins = market == CRYPTO
    data = load_crypto(data_dir, with_factors=True) if coins else load_market(data_dir, market, with_factors=True)
    if coins:
        config = replace(config, horizons=CRYPTO_HORIZONS)
    usd_fx_fee_pct = repo.fee_settings(conn)[1 if coins else 0]  # coins pay the crypto fee instead
    variants: dict[str, dict] = {}
    runs: dict[str, tuple[WalkForward, tuple[int, ...]]] = {}
    scores: dict[str, Scores] = {}
    results: list[BenchmarkResult] = []
    reference = None
    for name, variant in ABLATIONS.items():
        if variant is None:  # the policy row runs once a model is chosen
            continue
        plan = unbuilt(variant)
        if plan is not None:
            variants[name] = {"status": "not built", "plan": plan}
            continue
        began = time.monotonic()
        wf = run_variant(data, variant, config)
        pred = wf.predictions
        keys = _keys(pred)
        if reference is None:  # the baseline runs first
            reference = keys
        elif not keys.equals(reference):
            raise ValueError(f"{name} scored different rows than the baseline")
        model = model_metrics(pred)
        means = summary(model, config.horizons)
        usable = calibrated_horizons(model)
        policy = policy_metrics(pred[pred["p"].notna() & pred["horizon"].isin(usable)], market, usd_fx_fee_pct)
        variants[name] = {
            "status": "run", "seconds": round(time.monotonic() - began, 1),
            "model": model, "summary": means, "policy": policy,
        }
        if variant.factors:
            variants[name]["alpha_rank_ic"] = wf.alpha_rank_ic
            variants[name]["fallback_count"] = wf.fallback_count
            if market == Market.US and data.factors is not None:
                variants[name]["french"] = french_cross_check(data.factors.daily)
        scores[name] = Scores.of(model, config.horizons)
        runs[name] = (wf, usable)
        results += [
            BenchmarkResult(str(market), name, fold, json_safe({
                "model": model[fold], "summary": means[fold], "policy": policy.get(fold),
            }))
            for fold in model
        ]

    active = repo.active_config(conn, str(market))
    active_name = _model_name(active.config) if active else None
    incumbent = (active_name, scores[active_name]) if active_name in scores and active_name != "baseline" else None
    others = {name: s for name, s in scores.items() if name != "baseline"}
    chosen, decisions = choose_model(scores["baseline"], others, incumbent)

    began = time.monotonic()
    panel = daily_panel(data_dir, market)
    wf, usable = runs[chosen]
    model_config = ABLATIONS[chosen]
    policy_report, policy_decision, policy, final_reason = _policy_row(
        data, model_config, wf, usable, panel, market, usd_fx_fee_pct, config
    )
    del panel  # the daily panel is large; free it before the next market
    variants[POLICY_ROW] = {
        "status": "run", "model": chosen, "seconds": round(time.monotonic() - began, 1), "policy": policy_report,
    }
    decisions[POLICY_ROW] = policy_decision
    candidate = policy_report["candidate"]
    for k, default in enumerate(policy_report["default"]["per_period"], start=1):
        tuned = candidate["per_period"][k - 1] if candidate else None
        results.append(BenchmarkResult(str(market), POLICY_ROW, str(k), json_safe({"default": default, "candidate": tuned})))
    results.append(BenchmarkResult(str(market), POLICY_ROW, "pooled", json_safe({
        "default": policy_report["default"]["pooled"], "candidate": candidate["pooled"] if candidate else None,
    })))

    repo.write_benchmark_results(conn, run_id, results)
    stored = replace(model_config, policy=policy).to_json()
    if active is not None and stored == active.config:
        accepted = {"changed": False, "reason": "unchanged", "config": active.config}
    else:
        if policy is not None:
            reason = policy_decision.reasons[0]
        elif policy_decision.accepted:  # passed on the outer folds, but the whole-history tune found nothing
            reason = f"the tuned policy passed but couldn't be re-tuned ({final_reason}): today's rules"
        elif active is None and chosen == "baseline":
            reason = FIRST
        elif chosen == "baseline":
            reason = "no addition passed on the outer folds: baseline"
        else:
            reason = decisions[chosen].reasons[0]
        repo.accept_config(conn, str(market), stored, reason, run_id, now)
        accepted = {"changed": True, "reason": reason, "config": stored}
    return {
        "horizons": list(config.horizons),
        "variants": variants,
        "decisions": {n: {"accepted": d.accepted, "reasons": list(d.reasons)} for n, d in decisions.items()},
        "chosen": chosen,
        "accepted": accepted,
    }


def _constants(config: TrainConfig) -> dict:
    return {
        "outer_folds": config.folds, "min_train_years": config.min_train_years,
        "inner_splits": INNER_SPLITS, "inner_min_train_years": INNER_MIN_TRAIN_YEARS,
        "pinball_tolerance": PINBALL_TOLERANCE, "min_folds_improved": MIN_FOLDS_IMPROVED,
        "max_calibration_pts": MAX_CALIBRATION_PTS, "seed": config.params.get("seed"),
        "rounds": config.rounds, "sample_every": SAMPLE_EVERY,
    }


def run(
    data_dir: Path,
    markets: Sequence[Market],
    conn: psycopg.Connection,
    now: datetime,
    git_sha: str | None,
    train_config: TrainConfig = TrainConfig(),  # noqa: B008
) -> dict:
    """The whole benchmark; the run row is finished even when something unexpected fails."""
    began = time.monotonic()
    run_id = repo.start_benchmark_run(conn, now, git_sha)
    report: dict[str, Any] = {
        "run_id": run_id, "started_at": now.isoformat(), "git_sha": git_sha, "status": "failed",
        "constants": _constants(train_config), "markets": {},
    }
    try:
        for market in markets:
            if market == CRYPTO and (skipped := crypto_skipped(data_dir)):
                report["markets"][CRYPTO] = {"skipped": skipped}
                continue
            try:
                report["markets"][str(market)] = _benchmark_market(data_dir, market, conn, run_id, now, train_config)
            except Exception as e:  # one market's failure must not stop the other
                report["markets"][str(market)] = {"error": f"{type(e).__name__}: {e}"}
        report["status"] = "failed" if exit_code(report) else "success"
    finally:
        report = json_safe(report)
        finished = now + timedelta(seconds=time.monotonic() - began)
        repo.finish_benchmark_run(conn, run_id, finished, report["status"], report)
    return report


def exit_code(report: Mapping[str, Any]) -> int:
    return 1 if any("error" in m for m in report["markets"].values()) else 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark every built ablation and accept a configuration.")
    parser.add_argument("--data", required=True, type=Path, help="the training data directory")
    parser.add_argument("--out", required=True, type=Path, help="where to write the report files")
    parser.add_argument(
        "--market", action="append", choices=[*(m.value for m in Market), CRYPTO],
        help="a market to benchmark (repeatable; default all)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    markets = [CRYPTO if m == CRYPTO else Market(m) for m in args.market] if args.market else MARKET_ORDER
    with connect(Settings.from_env().database_url) as conn:
        report = run(args.data, markets, conn, datetime.now(UTC), os.environ.get("GITHUB_SHA"))
    write_reports(report, args.out)
    print(render_markdown(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
