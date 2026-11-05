"""The weekly job: train each market's model, backtest it, store it, and promote it if it earns it.

Run as `python -m advisor.model.weekly --data DIR` after the training data is built. A model is
stored every week; it only becomes the active one when its probabilities are honest and its
ranking is no worse than the active model's. A market that fails is reported and the rest carry on.
"""

import argparse
import json
import math
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from advisor.config import Settings
from advisor.model.backtest import (
    MAX_CALIBRATION_PTS,
    gate,
    pick_funnel,
    pick_metrics,
    simulate_picks,
)
from advisor.model.crypto import CRYPTO, CRYPTO_HORIZONS, load_crypto
from advisor.model.dataset import load_market
from advisor.model.train import TrainConfig, to_files
from advisor.model.variants import BASELINE, ModelConfig, fit_variant, run_variant
from advisor.models import Market, StoredModel
from advisor.policy import DEFAULT_POLICY
from advisor.store import repo
from advisor.store.db import connect

IC_TOLERANCE = 0.005  # week-to-week noise: one more week of data must not block a good replacement
KIND = {Market.US: "stock_us", Market.TSX: "stock_tsx", CRYPTO: "crypto"}
COINS_NEVER_PICKS = "coins are never picks (spec §5.4)"
# TSX first: it is the smaller load, so an out-of-memory kill during US (which no `try` can catch)
# still leaves TSX trained and reported
TRAIN_ORDER = [Market.TSX, Market.US]
REPORT = "model-report.json"
TOP_FEATURES = 10
MAX_MODEL_AGE = timedelta(days=28)  # after this, any honest model replaces the active one


def version_for(market: Market, trained_at: datetime) -> str:
    return f"{KIND[market]}-{trained_at:%Y%m%d%H%M}"


def _nan(x: float | None) -> bool:
    return x is None or x != x


def should_promote(
    metrics: Mapping[str, Any], calibration_pts: float, active: StoredModel | None, now: datetime
) -> tuple[bool, str]:
    """Fails closed: a check that couldn't be measured never promotes.

    The IC comparison is against the IC the active model recorded on its own window, so a lucky
    week raises the bar; past MAX_MODEL_AGE any model that passes calibration replaces it.
    """
    if _nan(calibration_pts):
        return False, "probabilities couldn't be checked (no calibrated predictions)"
    if calibration_pts > MAX_CALIBRATION_PTS:
        return False, f"probabilities off by {calibration_pts:.1f} points (limit {MAX_CALIBRATION_PTS:g})"
    new_ic = metrics["mean_rank_ic"]
    if _nan(new_ic):
        return False, "rank IC couldn't be measured"
    if active is None:
        return True, "first model"
    age = now - active.trained_at
    if age >= MAX_MODEL_AGE:
        return True, f"the active model is {age.days} days old (limit {MAX_MODEL_AGE.days})"
    old_ic = active.metrics.get("mean_rank_ic")
    if _nan(old_ic):
        return False, "rank IC couldn't be measured"
    return new_ic >= old_ic - IC_TOLERANCE, f"rank IC {new_ic:.3f} vs the active {old_ic:.3f}"


def usable_horizons(
    metrics: Mapping[int, Mapping[str, float]], horizons: Sequence[int]
) -> tuple[int, ...]:
    """The horizons whose calibration was measured and is within the limit; the rest give no forecasts."""
    return tuple(
        h for h in horizons
        if h in metrics and not _nan(metrics[h]["calibration_pts"])
        and metrics[h]["calibration_pts"] <= MAX_CALIBRATION_PTS
    )


def calibration_of(metrics: Mapping[int, Mapping[str, float]], horizons: Sequence[int]) -> float:
    """The worst horizon's calibration gap; NaN if any is NaN or any expected horizon is unmeasured.

    Python's `max` over floats depends on the order of a NaN, so it can't be used here.
    """
    if not horizons or any(h not in metrics for h in horizons):
        return float("nan")
    values = [metrics[h]["calibration_pts"] for h in horizons]
    if any(v != v for v in values):
        return float("nan")
    return max(values)


def _mean_or_nan(values: Sequence[float]) -> float:
    values = [v for v in values if v == v]
    return sum(values) / len(values) if values else float("nan")


def json_safe(value: Any) -> Any:
    """JSON-safe: NaN becomes null, numpy numbers plain ones, Timestamps ISO strings."""
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def config_for(conn: psycopg.Connection, market: Market | str) -> tuple[ModelConfig, str]:
    """The market's accepted configuration, or the baseline when there is none or this code can't run it."""
    row = repo.active_config(conn, str(market))
    if row is None:
        return BASELINE, "no accepted configuration yet: baseline"
    try:
        config = ModelConfig.from_json(row.config)
    except ValueError as error:
        return BASELINE, f"accepted configuration #{row.id} can't be used ({error}): baseline"
    return config, f"accepted configuration #{row.id} ({config.name})"


def _train_market(
    data_dir: Path, market: Market | str, conn: psycopg.Connection, now: datetime, config: TrainConfig
) -> dict:
    kind = KIND[market]
    coins = market == CRYPTO
    began = time.monotonic()
    model_config, config_reason = config_for(conn, market)
    if coins:
        config = replace(config, horizons=CRYPTO_HORIZONS)
    data = (
        load_crypto(data_dir, with_factors=model_config.factors, with_garch=model_config.garch)
        if coins else load_market(data_dir, market, with_factors=model_config.factors, with_garch=model_config.garch)
    )
    loaded = time.monotonic()
    wf = run_variant(data, model_config, config)
    walked = time.monotonic()
    usable = usable_horizons(wf.metrics, config.horizons)
    calibrated = wf.predictions[wf.predictions["p"].notna() & wf.predictions["horizon"].isin(usable)]
    usd_fx_fee_pct = repo.fee_settings(conn)[0]
    policy = model_config.policy or DEFAULT_POLICY
    # with no usable horizon, the worst of all gives the plain-words reason
    calibration_pts = calibration_of(wf.metrics, usable or config.horizons)
    if coins:  # coins never enter the pick lists, so there is no picks gate to backtest
        backtest: dict = {"funnel": None}
        picks_enabled, picks_reason = False, COINS_NEVER_PICKS
    else:
        backtest = {
            **pick_metrics(simulate_picks(calibrated, market, usd_fx_fee_pct, policy)),
            "funnel": pick_funnel(calibrated, market, usd_fx_fee_pct, policy),
        }
        picks_enabled, picks_reason = gate(backtest, calibration_pts)
    model = fit_variant(data, wf, model_config, config)
    files = to_files(model)
    seconds = {
        "load": round(loaded - began, 1),
        "walk_forward": round(walked - loaded, 1),
        "final": round(time.monotonic() - walked, 1),
    }
    mean_rank_ic = _mean_or_nan([m["rank_ic"] for m in wf.metrics.values()])
    importance = {}
    for h in model.horizons:
        gain = model.boosters[h][model.p_source].feature_importance("gain")
        top = sorted(zip(model.features, gain, strict=True), key=lambda p: -p[1])[:TOP_FEATURES]
        importance[h] = {name: float(g) for name, g in top}
    metrics = json_safe({
        "horizons": wf.metrics, "mean_rank_ic": mean_rank_ic, "backtest": backtest,
        "picks_enabled": picks_enabled, "picks_reason": picks_reason, "rows": len(data.rows),
        "folds": [[f.start, f.end] for f in wf.folds], "features": model.features,
        "importance": importance, "seconds": seconds,
        "usable_horizons": list(usable), "config": model_config.to_json(),
    })
    version = version_for(market, now)
    repo.save_model(conn, version, kind, now, metrics, json_safe(calibration_pts), files)
    promoted, reason = should_promote(metrics, calibration_pts, repo.active_model(conn, kind), now)
    if promoted:
        repo.activate_model(conn, kind, version)
    repo.prune_models(conn, kind)
    return {
        "version": version, "promoted": promoted, "reason": reason, "picks_enabled": picks_enabled,
        "picks_reason": picks_reason, "calibration_pts": json_safe(calibration_pts),
        "mean_rank_ic": json_safe(mean_rank_ic), "seconds": seconds,
        "usable_horizons": list(usable), "funnel": metrics["backtest"]["funnel"],
        "config": model_config.name, "config_reason": config_reason,
    }


def run(
    data_dir: Path,
    markets: Sequence[Market],
    conn: psycopg.Connection,
    now: datetime,
    config: TrainConfig = TrainConfig(),  # noqa: B008
    crypto: bool = True,
) -> dict[str, dict]:
    report: dict[str, dict] = {}
    for market in markets:
        try:
            report[str(market)] = _train_market(data_dir, market, conn, now, config)
        except Exception as e:  # one market's failure must not stop the other
            report[str(market)] = {"error": f"{type(e).__name__}: {e}"}
    if crypto:
        skipped = crypto_skipped(data_dir)
        if skipped:
            report[CRYPTO] = {"skipped": skipped}
        else:
            try:
                report[CRYPTO] = _train_market(data_dir, CRYPTO, conn, now, config)
            except Exception as e:
                report[CRYPTO] = {"error": f"{type(e).__name__}: {e}"}
    return report


def crypto_skipped(data_dir: Path) -> str | None:
    """Why this build can't train the coin model, or None when it can."""
    manifest = json.loads((data_dir / "manifest.json").read_text())
    if "crypto_error" in manifest:
        return f"the crypto history failed to build: {manifest['crypto_error']}"
    if not (data_dir / "prices_crypto.parquet").exists():
        return "no crypto history in this build"
    return None


def exit_code(report: Mapping[str, Mapping]) -> int:
    return 1 if any("error" in r for r in report.values()) else 0


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train, backtest and promote the stock models.")
    parser.add_argument("--data", required=True, type=Path, help="the training data directory")
    parser.add_argument(
        "--market", action="append", choices=[m.value for m in Market],
        help="a market to train (repeatable; default both)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    markets = [Market(m) for m in args.market] if args.market else TRAIN_ORDER
    with connect(Settings.from_env().database_url) as conn:
        report = run(args.data, markets, conn, datetime.now(UTC), crypto=not args.market)
    text = json.dumps(report, indent=2)
    (args.data / REPORT).write_text(text)
    print(text)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
