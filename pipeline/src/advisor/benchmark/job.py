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
    INCUMBENT_CALIBRATION_PTS,
    MIN_FOLDS_IMPROVED,
    PINBALL_TOLERANCE,
    Decision,
    Scores,
    accept_policy,
    choose_model,
)
from advisor.benchmark.folds import INNER_MIN_TRAIN_YEARS, INNER_SPLITS
from advisor.benchmark.metrics import (
    calibrated_horizons,
    model_metrics,
    policy_metrics,
    summary,
    top_slice,
)
from advisor.benchmark.policy_search import score, score_each, tune_for_outer
from advisor.benchmark.report import render_markdown, write_reports
from advisor.benchmark.simulate import DailyPanel, daily_panel
from advisor.config import Settings
from advisor.model.backtest import MAX_CALIBRATION_PTS
from advisor.model.crypto import CRYPTO, CRYPTO_HORIZONS, load_crypto
from advisor.model.dataset import SAMPLE_EVERY, MarketData, load_market
from advisor.model.factors import french_cross_check
from advisor.model.groups import DATA_GROUPS
from advisor.model.train import BAG_SEEDS, Fold, TrainConfig, WalkForward
from advisor.model.variants import (
    BASELINE,
    ModelConfig,
    data_groups,
    missing_groups,
    run_variant,
    unbuilt,
)
from advisor.model.weekly import crypto_skipped, json_safe
from advisor.models import BenchmarkResult, Market
from advisor.policy import DEFAULT_POLICY, Policy
from advisor.store import repo
from advisor.store.db import connect

# The base the US data group rows build on: each adds one group's features to it, and must beat it.
GROUP_BASE = "garch+ranker+forest"
_GROUP_BASE_CONFIG = ModelConfig(ranker=True, garch=True, forest=True)
# One row per US data group, in `DATA_GROUPS` order.
GROUP_ROWS: dict[str, ModelConfig] = {
    config.name: config for config in (replace(_GROUP_BASE_CONFIG, **{group: True}) for group in DATA_GROUPS)
}

# The ablation rows, in report order. The last is the chosen model plus a policy tuned for it.
# Retired in Plan 7b (rejected in every market by the benchmarks of 2026-11-03 and 2026-11-15):
# factors, extras, ranker+extras and ranker+extras+bagged.
ABLATIONS: dict[str, ModelConfig | None] = {
    "baseline": BASELINE,
    "ranker": ModelConfig(ranker=True),
    "garch": ModelConfig(garch=True),
    "factors+garch": ModelConfig(factors=True, garch=True),
    "garch+ranker": ModelConfig(ranker=True, garch=True),
    GROUP_BASE: _GROUP_BASE_CONFIG,
    "ranker+earnings": ModelConfig(ranker=True, earnings=True),
    **GROUP_ROWS,
    "full+policy": None,
}
POLICY_ROW = "full+policy"
US_ONLY = {"ranker+earnings", *GROUP_ROWS}  # SEC filings and the data groups cover US companies only


def rows_for(market: Market | str) -> dict[str, ModelConfig | None]:
    """The ablation rows the market runs, in report order."""
    return {name: c for name, c in ABLATIONS.items() if market == Market.US or name not in US_ONLY}


def base_row(config: ModelConfig) -> ModelConfig | None:
    """The config with no bagging and no data group: the row a bagged or data group row must also beat.
    None when that is the config itself."""
    base = replace(config, bagged=False, **dict.fromkeys(DATA_GROUPS, False))
    return None if base == config else base


def base_rows(ablations: Mapping[str, ModelConfig | None]) -> dict[str, str]:
    """Each row that has a base row, and that row's name: seed averaging's triple cost and a data
    group's download are paid only for a measured gain over the same model without them."""
    rows = {}
    for name, config in ablations.items():
        base = None if config is None else base_row(config)
        if base is None:
            continue
        found = next((n for n, c in ablations.items() if c == base), None)
        if found is None:
            raise ValueError(f"{name} has no base row")
        rows[name] = found
    return rows


BASE_ROWS = base_rows(ABLATIONS)


def combined_config(passed: Sequence[str]) -> ModelConfig | None:
    """`GROUP_BASE`'s config with each data group that passed on its own turned on; None with fewer than two."""
    groups = list(dict.fromkeys(passed))
    if len(groups) < 2:
        return None
    return replace(ABLATIONS[GROUP_BASE], **dict.fromkeys(groups, True))


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


def _same_config(stored: Mapping[str, Any], active: Mapping[str, Any]) -> bool:
    """Whether two stored configs mean the same thing: an active config saved as version 1 equals
    the same config written now. One this code can't read is never the same."""
    try:
        return ModelConfig.from_json(stored) == ModelConfig.from_json(active)
    except ValueError:
        return False


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
    data = (
        load_crypto(data_dir, with_factors=True, with_garch=True)
        if coins else load_market(data_dir, market, with_factors=True, with_garch=True)
    )
    if coins:
        config = replace(config, horizons=CRYPTO_HORIZONS)
    usd_fx_fee_pct = repo.fee_settings(conn)[1 if coins else 0]  # coins pay the crypto fee instead
    variants: dict[str, dict] = {}
    runs: dict[str, tuple[WalkForward, tuple[int, ...]]] = {}
    scores: dict[str, Scores] = {}
    # every row this run scored, by name: the fixed rows, the combined row and the incumbent's row
    configs: dict[str, ModelConfig] = {}
    results: list[BenchmarkResult] = []
    reference = None

    def score_row(name: str, variant: ModelConfig) -> None:
        nonlocal reference
        plan = unbuilt(variant)
        if plan is not None:
            variants[name] = {"status": "not built", "plan": plan}
            return
        if missing := missing_groups(data, variant):  # fails closed: no score, so no decision
            variants[name] = {"status": "no data", "groups": missing}
            return
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
        top = top_slice(pred, market, usd_fx_fee_pct)
        variants[name] = {
            "status": "run", "seconds": round(time.monotonic() - began, 1),
            "model": model, "summary": means, "policy": policy, "top_slice": top,
        }
        if variant.garch:
            variants[name]["garch"] = {"fallbacks": wf.garch_fallbacks}
        if variant.factors:
            variants[name]["alpha_rank_ic"] = wf.alpha_rank_ic
            variants[name]["fallback_count"] = wf.fallback_count
            if market == Market.US and data.factors is not None:
                variants[name]["french"] = french_cross_check(data.factors.daily)
        scores[name] = Scores.of(model, config.horizons)
        runs[name] = (wf, usable)
        configs[name] = variant
        results.extend(
            BenchmarkResult(str(market), name, fold, json_safe({
                "model": model[fold], "summary": means[fold], "policy": policy.get(fold),
                "top_slice": top.get(fold),
            }))
            for fold in model
        )

    for name, variant in rows_for(market).items():
        if variant is not None:  # the policy row runs once a model is chosen
            score_row(name, variant)

    # the data group rows that beat both the baseline and their base row, combined into one more row
    twins = dict(BASE_ROWS)
    group_rows = [name for name in scores if BASE_ROWS.get(name) == GROUP_BASE]
    combined = None
    if len(group_rows) >= 2:
        others = {name: s for name, s in scores.items() if name != "baseline"}
        _, strict = choose_model(scores["baseline"], others, None, BASE_ROWS)
        passed = [group for name in group_rows if strict[name].accepted for group in data_groups(configs[name])]
        combined = combined_config(passed)
    if combined is not None and combined.name not in variants:
        score_row(combined.name, combined)
        twins[combined.name] = GROUP_BASE

    # the accepted configuration is scored even when it has no row here (a retired or combined row),
    # so the incumbent rule still holds
    active = repo.active_config(conn, str(market))
    active_name = _model_name(active.config) if active else None
    if active_name is not None and active_name not in variants:
        score_row(active_name, replace(ModelConfig.from_json(active.config), policy=None))
    incumbent = (active_name, scores[active_name]) if active_name in scores and active_name != "baseline" else None
    others = {name: s for name, s in scores.items() if name != "baseline"}
    chosen, decisions = choose_model(scores["baseline"], others, incumbent, twins)

    def outcome(chosen: str, accepted: dict) -> dict:
        return {
            "horizons": list(config.horizons),
            "variants": variants,
            "decisions": {n: {"accepted": d.accepted, "reasons": list(d.reasons)} for n, d in decisions.items()},
            "chosen": chosen,
            "accepted": accepted,
            "combined": combined.name if combined is not None else None,
        }

    held = variants.get(active_name) if active_name is not None else None
    if held is not None and held.get("status") == "no data":
        # this build lacks the accepted config's data: missing evidence is not a measured loss, so the
        # accepted config stays and no policy is tuned this run (Ruling R15); every other row is reported
        groups = list(held["groups"])
        variants[POLICY_ROW] = {"status": "no data", "groups": groups}
        repo.write_benchmark_results(conn, run_id, results)
        reason = f"unchanged: {active_name} has no data: {', '.join(groups)}"
        return outcome(active_name, {"changed": False, "reason": reason, "config": active.config})

    began = time.monotonic()
    panel = daily_panel(data_dir, market)
    wf, usable = runs[chosen]
    model_config = configs[chosen]
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
    if active is not None and _same_config(stored, active.config):
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
    return outcome(chosen, accepted)


def _constants(config: TrainConfig) -> dict:
    return {
        "outer_folds": config.folds, "min_train_years": config.min_train_years,
        "inner_splits": INNER_SPLITS, "inner_min_train_years": INNER_MIN_TRAIN_YEARS,
        "pinball_tolerance": PINBALL_TOLERANCE, "min_folds_improved": MIN_FOLDS_IMPROVED,
        "max_calibration_pts": MAX_CALIBRATION_PTS, "incumbent_calibration_pts": INCUMBENT_CALIBRATION_PTS,
        "seed": config.params.get("seed"), "bag_seeds": list(BAG_SEEDS),
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
