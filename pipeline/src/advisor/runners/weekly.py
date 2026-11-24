"""The weekly runners backtest, run on the training build's files inside the training job.

Run as `python -m advisor.runners.weekly --data DIR` after the training data is built. The first run
freezes its pick as the next rule version (1 on a new database); later runs only report, against the
live rule. Only the owner
switches the live rule (supabase/manual/runners_switch_rule.sql). A failure is logged and exits 1; it
never fails the training job.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

from advisor.runners.backtest import load_series, run_backtest, sessions_of
from advisor.runners.rule import Rule
from advisor.store import repo
from advisor.store.db import connect

log = logging.getLogger(__name__)

STORED = ("data_from", "data_to", "cutoff", "variants_tried", "pick", "split_suspect")


def _prices(data: Path) -> pd.DataFrame:
    """The build's US prices without its last day's bar, as `load_market` reads them."""
    manifest = json.loads((data / "manifest.json").read_text())
    if "failed" in manifest:  # its files are partial, or left over from an earlier build
        raise ValueError(f"the training data build failed: {manifest['failed']['error']}")
    prices = pd.read_parquet(data / "prices_US.parquet")
    # the build ran during its last session, so that day's bar is partial
    return prices[pd.to_datetime(prices["day"]) < pd.Timestamp(manifest["end"])]


def run(conn: psycopg.Connection, data: Path) -> dict:
    """Backtest and store the result. With no rule yet, the pick becomes version 1."""
    prices = _prices(data)
    events = pd.read_parquet(data / "events_US.parquet")
    live = repo.live_runner_rule(conn)
    frozen = None if live is None else Rule.from_settings(live[1])
    result = run_backtest(load_series(prices, events), sessions_of(prices), frozen)
    row = {key: result[key] for key in STORED}
    if live is not None:
        repo.insert_runner_backtest(conn, row | {"rule_version": live[0], "frozen": result["frozen"]})
        return result

    pick = result["pick"]
    result["frozen"] = {key: pick[key] for key in ("settings", "older", "newer")}
    # one transaction: a failed freeze leaves no backtest naming a version that does not exist. The
    # backtest names the version the freeze made: older rule rows may exist with none live.
    with conn.transaction():
        version = repo.freeze_runner_rule(conn, pick["settings"], None)
        backtest_id = repo.insert_runner_backtest(conn, row | {"rule_version": version, "frozen": result["frozen"]})
        repo.set_runner_rule_backtest(conn, version, backtest_id)
    return result


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the runner rule on the training build's files.")
    parser.add_argument("--data", required=True, type=Path, help="the training data directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with connect(os.environ["DATABASE_URL"]) as conn:
            result = run(conn, args.data)
    except Exception:
        log.exception("the runners backtest failed")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
