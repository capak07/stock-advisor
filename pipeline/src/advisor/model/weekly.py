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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from advisor.config import Settings
from advisor.model.backtest import MAX_CALIBRATION_PTS, gate, pick_metrics, simulate_picks
from advisor.model.dataset import load_market
from advisor.model.train import TrainConfig, fit_final, to_files, walk_forward
from advisor.models import Market, StoredModel
from advisor.store import repo
from advisor.store.db import connect

IC_TOLERANCE = 0.005  # week-to-week noise: one more week of data must not block a good replacement
KIND = {Market.US: "stock_us", Market.TSX: "stock_tsx"}
REPORT = "model-report.json"
TOP_FEATURES = 10


def version_for(market: Market, trained_at: datetime) -> str:
    return f"{KIND[market]}-{trained_at:%Y%m%d%H%M}"


def _nan(x: float | None) -> bool:
    return x is None or x != x


def should_promote(
    metrics: Mapping[str, Any], calibration_pts: float, active: StoredModel | None
) -> tuple[bool, str]:
    """Fails closed: a check that couldn't be measured never promotes."""
    if _nan(calibration_pts):
        return False, "probabilities couldn't be checked (no calibrated predictions)"
    if calibration_pts > MAX_CALIBRATION_PTS:
        return False, f"probabilities off by {calibration_pts:.1f} points (limit {MAX_CALIBRATION_PTS:g})"
    new_ic = metrics["mean_rank_ic"]
    if _nan(new_ic):
        return False, "rank IC couldn't be measured"
    if active is None:
        return True, "first model"
    old_ic = active.metrics.get("mean_rank_ic")
    if _nan(old_ic):
        return False, "rank IC couldn't be measured"
    return new_ic >= old_ic - IC_TOLERANCE, f"rank IC {new_ic:.3f} vs the active {old_ic:.3f}"


def _max_or_nan(values: Sequence[float]) -> float:
    """The largest value, NaN if any is NaN or there are none (Python's max depends on order)."""
    if not values or any(v != v for v in values):
        return float("nan")
    return max(values)


def _mean_or_nan(values: Sequence[float]) -> float:
    values = [v for v in values if v == v]
    return sum(values) / len(values) if values else float("nan")


def _clean(value: Any) -> Any:
    """JSON-safe: NaN becomes null, numpy numbers plain ones, Timestamps ISO strings."""
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _train_market(
    data_dir: Path, market: Market, conn: psycopg.Connection, now: datetime, config: TrainConfig
) -> dict:
    kind = KIND[market]
    began = time.monotonic()
    data = load_market(data_dir, market)
    loaded = time.monotonic()
    wf = walk_forward(data, config)
    walked = time.monotonic()
    calibrated = wf.predictions[wf.predictions["p"].notna()]
    backtest = pick_metrics(simulate_picks(calibrated, market, repo.fee_settings(conn)[0]))
    calibration_pts = _max_or_nan([m["calibration_pts"] for m in wf.metrics.values()])
    picks_enabled, picks_reason = gate(backtest, calibration_pts)
    model = fit_final(data, wf, config)
    files = to_files(model)
    seconds = {
        "load": round(loaded - began, 1),
        "walk_forward": round(walked - loaded, 1),
        "final": round(time.monotonic() - walked, 1),
    }
    mean_rank_ic = _mean_or_nan([m["rank_ic"] for m in wf.metrics.values()])
    importance = {}
    for h in model.horizons:
        gain = model.boosters[h]["beat"].feature_importance("gain")
        top = sorted(zip(model.features, gain, strict=True), key=lambda p: -p[1])[:TOP_FEATURES]
        importance[h] = {name: float(g) for name, g in top}
    metrics = _clean({
        "horizons": wf.metrics, "mean_rank_ic": mean_rank_ic, "backtest": backtest,
        "picks_enabled": picks_enabled, "picks_reason": picks_reason, "rows": len(data.rows),
        "folds": [[f.start, f.end] for f in wf.folds], "features": model.features,
        "importance": importance, "seconds": seconds,
    })
    version = version_for(market, now)
    repo.save_model(conn, version, kind, now, metrics, _clean(calibration_pts), files)
    promoted, reason = should_promote(metrics, calibration_pts, repo.active_model(conn, kind))
    if promoted:
        repo.activate_model(conn, kind, version)
    repo.prune_models(conn, kind)
    return {
        "version": version, "promoted": promoted, "reason": reason, "picks_enabled": picks_enabled,
        "picks_reason": picks_reason, "calibration_pts": _clean(calibration_pts),
        "mean_rank_ic": _clean(mean_rank_ic), "seconds": seconds,
    }


def run(
    data_dir: Path,
    markets: Sequence[Market],
    conn: psycopg.Connection,
    now: datetime,
    config: TrainConfig = TrainConfig(),  # noqa: B008
) -> dict[str, dict]:
    report: dict[str, dict] = {}
    for market in markets:
        try:
            report[str(market)] = _train_market(data_dir, market, conn, now, config)
        except Exception as e:  # one market's failure must not stop the other
            report[str(market)] = {"error": f"{type(e).__name__}: {e}"}
    return report


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
    markets = [Market(m) for m in args.market] if args.market else list(Market)
    with connect(Settings.from_env().database_url) as conn:
        report = run(args.data, markets, conn, datetime.now(UTC))
    text = json.dumps(report, indent=2)
    (args.data / REPORT).write_text(text)
    print(text)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
