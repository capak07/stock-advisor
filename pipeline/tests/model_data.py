"""Synthetic training data in Plan 3a's file layout, for the model tests.

Each stock moves with the benchmark plus its own constant daily drift (drawn with sd 0.0012 ×
`signal`) and its own noise. Sharing the benchmark's moves keeps excess returns independent across
stocks, as in a real market, so past returns predict future excess returns when `signal` > 0 and
nothing does when it is 0.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from advisor.markets import MARKETS
from advisor.models import Market
from advisor.training.sectors import SECTOR_ETFS

STOCK_NOISE = 0.015  # sd of each stock's own daily log return, on top of the benchmark's


def _bars(symbol: str, closes: np.ndarray, days: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": symbol, "day": [d.date() for d in days], "open": closes, "high": closes * 1.01,
        "low": closes * 0.99, "close": closes, "volume": 1_000_000.0,
    })


def write_market(out: Path, market: Market, stocks: int = 40, days: int = 2340, seed: int = 7,
                 signal: float = 1.0, penny: bool = False) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    calendar = pd.bdate_range("2017-01-02", periods=days, name="day")
    suffix = ".TO" if market == Market.TSX else ""
    sectors = list(SECTOR_ETFS[market])[:2]
    symbols = [f"Q{chr(65 + i // 26)}{chr(65 + i % 26)}{suffix}" for i in range(stocks)]

    def walk(drift: float | np.ndarray, noise: float = 0.02) -> np.ndarray:
        return 50 * np.exp(np.cumsum(drift + rng.normal(0, noise, days)))

    moves = 0.0003 + rng.normal(0, 0.02, days)  # the benchmark's daily log returns
    frames = [_bars(MARKETS[market].benchmark, 50 * np.exp(np.cumsum(moves)), calendar)]
    frames += [_bars(etf, walk(0.0003), calendar) for etf in SECTOR_ETFS[market].values()]
    frames += [_bars(s, walk(moves + rng.normal(0, 0.0012 * signal), STOCK_NOISE), calendar) for s in symbols]
    labels = [(s, sectors[i % 2], "Industry") for i, s in enumerate(symbols)]
    if penny:
        frames.append(_bars(f"QZZ{suffix}", np.full(days, 0.5), calendar))
        labels.append((f"QZZ{suffix}", sectors[0], "Industry"))
    pd.concat(frames).to_parquet(out / f"prices_{market}.parquet", index=False)
    pd.DataFrame({"symbol": [], "day": [], "dividend": [], "split": []}).to_parquet(out / f"events_{market}.parquet", index=False)
    pd.DataFrame(labels, columns=["symbol", "sector", "industry"]).to_parquet(out / "sectors.parquet", index=False)
    if market == Market.US:
        pd.DataFrame(columns=["cik", "metric", "concept", "unit", "start", "end", "value", "filed", "form", "accession"]
                     ).to_parquet(out / "fundamentals.parquet", index=False)
        pd.DataFrame({"symbol": pd.Series([], dtype=str), "cik": pd.Series([], dtype="int32")}).to_parquet(out / "tickers.parquet", index=False)
    # built during the last day's session: its bar is partial and must be left out
    (out / "manifest.json").write_text(json.dumps({"end": calendar[-1].date().isoformat()}))
    return symbols


CRYPTO_START = pd.Timestamp("2020-01-04")  # a Saturday: every crypto row falls on one


def _coin_bars(symbol, days, close, volume):
    close = np.asarray(close, float)
    return pd.DataFrame({"symbol": symbol, "day": [d.date() for d in days], "open": close, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": volume})


def write_crypto(tmp, coins=6, days=600, seed=1):
    rng = np.random.default_rng(seed)
    cal = pd.date_range(CRYPTO_START, periods=days)
    walk = lambda sd: np.exp(np.cumsum(rng.normal(0, sd, days)))  # noqa: E731
    frames = [_coin_bars("BTC", cal, 100 * walk(0.03), 1e6)]
    frames += [_coin_bars(f"C{i:03d}", cal, 10 * walk(0.04), 1e5 * (i + 1)) for i in range(coins)]
    frames += [_coin_bars("USDT", cal, np.ones(days), 1e9), _coin_bars("FLAT", cal, np.full(days, 5.0), 1e9)]
    frames.append(_coin_bars("YOUNG", cal[-200:], 3 * walk(0.04)[-200:], 1e9))
    pd.concat(frames).to_parquet(tmp / "prices_crypto.parquet", index=False)
    weekdays = cal[cal.dayofweek < 5]
    spy = 400 * np.exp(np.cumsum(rng.normal(0, 0.01, len(weekdays))))
    _coin_bars("SPY", weekdays, spy, 1e7).to_parquet(tmp / "prices_US.parquet", index=False)
    (tmp / "manifest.json").write_text(json.dumps({"end": (cal[-1] + pd.Timedelta(days=1)).date().isoformat()}))
    return pd.concat(frames), _coin_bars("SPY", weekdays, spy, 1e7)


def _us_facts(cik: int = 1) -> pd.DataFrame:
    """Twelve quarters of revenue, operating income, diluted EPS and shares outstanding for one CIK, filed
    30 days after each quarter (the earnings and share-count features read them)."""
    rows = []
    for i, end in enumerate(pd.date_range("2016-03-31", periods=14, freq="QE")):
        start, filed = (end - pd.Timedelta(days=89)).date(), (end + pd.Timedelta(days=30)).date()
        for metric, concept, value in (
            ("revenue", "us-gaap:Revenues", 100.0 + 5 * i + (i % 3)),
            ("operating_income", "us-gaap:OperatingIncomeLoss", 10.0 + i),
            ("eps_diluted", "us-gaap:EarningsPerShareDiluted", 1.0 + 0.1 * i + 0.05 * (i % 2)),
        ):
            rows.append({"cik": cik, "metric": metric, "concept": concept, "unit": "USD", "start": start,
                         "end": end.date(), "value": value, "filed": filed, "form": "10-Q", "accession": f"a{i}"})
        rows.append({"cik": cik, "metric": "shares_outstanding", "concept": "dei:EntityCommonStockSharesOutstanding",
                     "unit": "shares", "start": None, "end": end.date(), "value": 2.0e7 + 1.0e5 * i,
                     "filed": filed, "form": "10-Q", "accession": f"a{i}"})
    return pd.DataFrame(rows)


def write_group_histories(out: Path, stocks: list[str]) -> None:
    """One small history file per data group source (the training layouts), for the first stock, spread
    over the whole calendar `write_market` wrote, so every group feature has a value on most days; plus
    `fundamentals.parquet` (quarterly facts and shares outstanding) and `tickers.parquet` mapping that
    stock to CIK 1, which the earnings, insider, events and share-count features need."""
    # imported here: model_data is imported by light tests too
    from advisor.model.holders import quarter_known

    symbol = stocks[0]
    prices = pd.read_parquet(out / "prices_US.parquet")
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(prices.loc[prices["symbol"] == MARKETS[Market.US].benchmark, "day"])))
    _us_facts().to_parquet(out / "fundamentals.parquet", index=False)
    pd.DataFrame({"symbol": [symbol], "cik": pd.Series([1], dtype="int32")}).to_parquet(
        out / "tickers.parquet", index=False)

    def write(name: str, rows: list[tuple], columns: list[str], **dtypes) -> None:
        frame = pd.DataFrame(rows, columns=columns)
        frame["symbol"] = frame["symbol"].astype("string")
        frame.astype(dtypes).to_parquet(out / name, index=False)

    write("short_interest.parquet", [
        (symbol, day.date(), 1_000_000 + 37_000 * (i % 9), 400_000.0 + 1_000 * i, 2.5 + 0.1 * (i % 5))
        for i, day in enumerate(cal[::10])
    ], ["symbol", "settlement", "short_interest", "avg_daily_volume", "days_to_cover"],
        short_interest="int64", avg_daily_volume="float64", days_to_cover="float64")
    write("short_volume.parquet", [
        (symbol, day.date(), 300_000.0 + 10_000.0 * (i % 7), 1_000_000.0) for i, day in enumerate(cal)
    ], ["symbol", "day", "short_volume", "total_volume"], short_volume="float64", total_volume="float64")
    actions, targets = ["up", "down", "main", "up", "init"], ["Raises", "Lowers", "Maintains"]
    write("analyst_events.parquet", [
        (symbol, day + pd.Timedelta(hours=15), "Firm", actions[i % 5], "Hold", "Buy", targets[i % 3])
        for i, day in enumerate(cal[::7])
    ], ["symbol", "graded_at", "firm", "action", "from_grade", "to_grade", "price_target_action"],
        graded_at="datetime64[ns]")
    items = [["5.02"], ["1.01", "9.01"], ["2.01"], ["4.02"], ["3.01"], ["2.02"]]
    write("material_events.parquet", [
        (symbol, f"8k-{i}", "8-K", day.date(), (day + pd.Timedelta(hours=21)).tz_localize("UTC"), items[i % 6])
        for i, day in enumerate(cal[::9])
    ], ["symbol", "accession", "form", "filing_date", "accepted_at", "items"])
    write("large_holders.parquet", [
        (symbol, f"dg-{i}", "SCHEDULE 13D" if i % 2 else "SC 13G", day.date(),
         pd.NaT if i % 3 == 0 else (day + pd.Timedelta(hours=20)).tz_localize("UTC"), bool(i % 2))
        for i, day in enumerate(cal[::25])
    ], ["symbol", "accession", "form", "filing_date", "accepted_at", "activist"],
        accepted_at="datetime64[ns, UTC]")
    write("insider_trades.parquet", [
        (symbol, f"f4-{i}", day.date(), (day + pd.Timedelta(hours=22)).tz_localize("UTC"),
         (day - pd.Timedelta(days=2)).date(), "P" if i % 2 == 0 else "S", 1_000.0 + i, 50.0,
         [f"Owner {i % 3}"], i % 4 == 0, False, False, symbol)
        for i, day in enumerate(cal[::11])
    ], ["symbol", "accession", "filing_date", "accepted_at", "trade_date", "code", "shares", "price", "owners",
        "officer", "director", "ten_percent_owner", "filed_ticker"], accepted_at="datetime64[ns, UTC]")
    periods = pd.date_range("2016-12-31", cal[-1], freq="QE")
    write("holders.parquet", [
        (symbol, "000000001", period.date(),
         quarter_known(period.date(), (period + pd.offsets.MonthEnd(2)).date()),
         500_000_000 + 1_000_000 * q, 100 + 3 * q - 5 * (q % 2))
        for q, period in enumerate(periods)
    ], ["symbol", "cusip", "period", "known", "shares", "holders"], shares="int64", holders="int64")
    reports = [
        (symbol, (period + pd.Timedelta(days=28)).normalize(), "after-close", 1.0 + 0.1 * q,
         1.0 + 0.1 * q + (0.05 if q % 3 else -0.02))
        for q, period in enumerate(pd.date_range("2016-03-31", cal[-1], freq="QE"))
    ]
    reports.append((symbol, cal[-1] + pd.Timedelta(days=40), None, 2.5, None))  # scheduled: no actual yet
    write("earnings_estimates.parquet", reports, ["symbol", "report_day", "timing", "eps_estimate", "eps_actual"],
          report_day="datetime64[ns]", eps_estimate="float64", eps_actual="float64")
    fda = [(symbol, "approval", day.date(), f"NDA{i}:original") for i, day in enumerate(cal[::40])]
    fda += [(symbol, "recall", day.date(), f"R{i}") for i, day in enumerate(cal[5::30])]
    fda += [(symbol, "recall", day.date(), f"R{i}") for i, day in enumerate(cal[20::30])]  # listed again later
    write("fda_events.parquet", fda, ["symbol", "kind", "day", "event_id"], kind="string", event_id="string")
