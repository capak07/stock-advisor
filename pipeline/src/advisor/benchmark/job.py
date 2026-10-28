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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from advisor.benchmark.accept import MIN_FOLDS_IMPROVED, PINBALL_TOLERANCE, Scores, choose_model
from advisor.benchmark.folds import INNER_MIN_TRAIN_YEARS, INNER_SPLITS
from advisor.benchmark.metrics import calibrated_horizons, model_metrics, policy_metrics, summary
from advisor.benchmark.report import render_markdown, write_reports
from advisor.config import Settings
from advisor.model.backtest import MAX_CALIBRATION_PTS
from advisor.model.dataset import SAMPLE_EVERY, load_market
from advisor.model.train import TrainConfig
from advisor.model.variants import BASELINE, ModelConfig, run_variant, unbuilt
from advisor.model.weekly import json_safe
from advisor.models import BenchmarkResult, Market
from advisor.store import repo
from advisor.store.db import connect

# The design's five ablation rows. The last is the chosen model plus a tuned policy (Plan 6e).
ABLATIONS: dict[str, ModelConfig | None] = {
    "baseline": BASELINE,
    "factors": ModelConfig(factors=True),
    "garch": ModelConfig(garch=True),
    "factors+garch": ModelConfig(factors=True, garch=True),
    "full+policy": None,
}
POLICY_PLAN = "Plan 6e"
FIRST = "first benchmark: today's model"
MARKET_ORDER = [Market.TSX, Market.US]  # the smaller load first, as in the weekly job


def _keys(predictions: pd.DataFrame) -> pd.DataFrame:
    return predictions[["day", "symbol", "horizon"]].sort_values(["day", "symbol", "horizon"]).reset_index(drop=True)


def _config_name(stored: Mapping[str, Any]) -> str | None:
    try:
        return ModelConfig.from_json(stored).name
    except ValueError:
        return None


def _benchmark_market(
    data_dir: Path, market: Market, conn: psycopg.Connection, run_id: int, now: datetime, config: TrainConfig
) -> dict:
    data = load_market(data_dir, market)
    usd_fx_fee_pct = repo.fee_settings(conn)[0]
    variants: dict[str, dict] = {}
    scores: dict[str, Scores] = {}
    results: list[BenchmarkResult] = []
    reference = None
    for name, variant in ABLATIONS.items():
        plan = POLICY_PLAN if variant is None else unbuilt(variant)
        if plan is not None:
            variants[name] = {"status": "not built", "plan": plan}
            continue
        began = time.monotonic()
        pred = run_variant(data, variant, config).predictions
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
        scores[name] = Scores.of(model, config.horizons)
        results += [
            BenchmarkResult(str(market), name, fold, json_safe({
                "model": model[fold], "summary": means[fold], "policy": policy.get(fold),
            }))
            for fold in model
        ]

    active = repo.active_config(conn, str(market))
    active_name = _config_name(active.config) if active else None
    incumbent = (active_name, scores[active_name]) if active_name in scores and active_name != "baseline" else None
    others = {name: s for name, s in scores.items() if name != "baseline"}
    chosen, decisions = choose_model(scores["baseline"], others, incumbent)

    repo.write_benchmark_results(conn, run_id, results)
    if active is not None and chosen == active_name:
        accepted = {"changed": False, "reason": "unchanged", "config": active.config}
    else:
        if active is None and chosen == "baseline":
            reason = FIRST
        elif chosen == "baseline":
            reason = "no addition passed on the outer folds: baseline"
        else:
            reason = decisions[chosen].reasons[0]
        stored = ABLATIONS[chosen].to_json()
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
        "--market", action="append", choices=[m.value for m in Market],
        help="a market to benchmark (repeatable; default all)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    markets = [Market(m) for m in args.market] if args.market else MARKET_ORDER
    with connect(Settings.from_env().database_url) as conn:
        report = run(args.data, markets, conn, datetime.now(UTC), os.environ.get("GITHUB_SHA"))
    write_reports(report, args.out)
    print(render_markdown(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
