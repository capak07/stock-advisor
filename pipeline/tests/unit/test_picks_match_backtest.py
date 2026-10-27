"""The live pick path must choose what the backtest's `simulate_picks` chose, or the gate vouches for nothing."""

import numpy as np
import pandas as pd
import pytest

from advisor.model.backtest import round_trip_cost, simulate_picks
from advisor.models import Market, PredictionRow
from advisor.recommend.picks import Choice, choose, rank_picks

HORIZONS = [5, 10, 20, 63]
SECTORS = ["Tech", "Banks", "Energy", "", None]
DAY = pd.Timestamp("2026-10-13")
FEE = 0.5
# coarse grids, so ratios tie and ranges sometimes have no width
Q50S = [-0.01, 0.002, 0.004, 0.012, 0.02, 0.04]
WIDTHS = [0.0, 0.02, 0.04, 0.08]
VOLUMES = [5e6, 2e7, float("nan")]


def frame(rng: np.random.Generator, market: Market) -> pd.DataFrame:
    rows = []
    for i in range(int(rng.integers(8, 30))):
        symbol = f"S{i:02d}"
        sector = SECTORS[int(rng.integers(len(SECTORS)))]  # a symbol has one sector and one volume
        volume = VOLUMES[int(rng.integers(len(VOLUMES)))]
        for horizon in HORIZONS:
            q50 = Q50S[int(rng.integers(len(Q50S)))]
            width = WIDTHS[int(rng.integers(len(WIDTHS)))]
            rows.append({
                "day": DAY, "symbol": symbol, "sector": sector, "horizon": horizon,
                "p": float(rng.choice([0.5, 0.58, 0.6, 0.7])), "q10": q50 - width / 2, "q50": q50,
                "q90": q50 + width / 2, "dollar_volume_20": volume, "y": float(rng.normal(0, 0.05)),
            })
    return pd.DataFrame(rows)


def live(df: pd.DataFrame, market: Market) -> list[tuple[str, int, str]]:
    choices: list[Choice] = []
    sectors: dict[str, str | None] = {}
    for symbol, g in df.groupby("symbol"):
        cost = float(round_trip_cost(market, g["dollar_volume_20"].to_numpy()[:1], FEE)[0])
        rows = [
            PredictionRow(symbol, int(r.horizon), r.q10, r.q50, r.q90, r.p, "BM", "v")
            for r in g.itertuples()
        ]
        picked = choose(rows, cost, sane=True)
        if picked:
            choices.append(picked)
        sectors[symbol] = g["sector"].iloc[0]
    return [(c.symbol, c.horizon, c.style) for c, _ in rank_picks(choices, sectors)]


@pytest.mark.parametrize("market", list(Market))
def test_live_picks_match_the_backtests_on_random_days(market):
    rng = np.random.default_rng(20261013)
    total = 0
    for _ in range(60):
        df = frame(rng, market)
        want = simulate_picks(df, market, FEE)
        expected = list(zip(want["symbol"], want["horizon"].astype(int), want["style"], strict=True))
        got = live(df, market)
        for style in ("swing", "position"):  # the lists are separate: compare each, order included
            assert [p for p in got if p[2] == style] == [p for p in expected if p[2] == style]
        total += len(got)
    assert total > 200  # the generator must produce picks, or the comparison is vacuous
