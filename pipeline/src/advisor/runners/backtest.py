"""The backtest: replay the ignition rule over the training build's prices, one setting at a time.

Pure: prices in, a JSON-ready dict out. A signal on D uses only bars dated on or before D; the trade
starts at D+1's open and settles as the live stage settles it. The pick reads the older two thirds only.
"""

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from advisor.runners.cost import cost_r, spread_pct
from advisor.runners.plan import gapped, plan_for, settle
from advisor.runners.rule import STARTING, Rule, Series, ignitions

MIN_TO_CHOOSE = 200  # older trades a variant needs before it can be picked
WORST = 10
COLUMNS = ["symbol", "signal_day", "entry_day", "status", "skip_reason", "gross_r", "cost_r", "net_r"]
PRICES = ["open", "high", "low", "close", "volume"]
GAPPED = "gapped up at the open"

# The fields the ignition test reads; the rest only shape the trade plan.
IGNITION_FIELDS = (
    "volume_x", "min_change", "min_close_pos", "min_dollar_volume",
    "price_min", "price_max", "quiet_sessions", "history_sessions",
)

# Each variant changes one setting of the base.
CHANGES: list[tuple[str, str, float | int | None]] = [
    ("volume 5x", "volume_x", 5.0),
    ("volume 20x", "volume_x", 20.0),
    ("change 15%", "min_change", 0.15),
    ("change 30%", "min_change", 0.30),
    ("close in the top quarter", "min_close_pos", 0.75),
    ("any close position", "min_close_pos", None),
    ("skip gaps over 15%", "gap_skip", 0.15),
    ("skip gaps over 25%", "gap_skip", 0.25),
    ("no stop floor", "stop_floor", None),
    ("stop floor 35%", "stop_floor", 0.35),
    ("target 1.5R", "target_r", 1.5),
    ("target 3R", "target_r", 3.0),
    ("hold 5", "hold_sessions", 5),
    ("hold 20", "hold_sessions", 20),
]

# Each symbol's signal sessions and split-suspect count, per ignition setting. Set by run_backtest so its
# variants share them; keyed on the symbol, which names one series only within that call.
_found: ContextVar[dict[tuple, tuple[np.ndarray, int]] | None] = ContextVar("runners_found", default=None)


def load_series(prices: pd.DataFrame, events: pd.DataFrame) -> dict[str, Series]:
    """Each symbol's adjusted bars, with the price it traded at rebuilt from its later splits.

    A row missing a price or its volume is dropped: one NaN would silence the running volume sums.
    Only symbols that ever traded inside $0.50-$5 are kept.
    """
    prices = prices.dropna(subset=PRICES)
    prices = prices.assign(stamp=pd.to_datetime(prices["day"])).sort_values(["symbol", "stamp"], kind="stable")
    splits = events[events["split"] > 0]  # dividend rows carry a zero ratio
    splits = splits.assign(stamp=pd.to_datetime(splits["day"])).sort_values("stamp", kind="stable")
    later = {symbol: _later_splits(frame) for symbol, frame in splits.groupby("symbol", sort=False)}

    out = {}
    for symbol, frame in prices.groupby("symbol", sort=True):
        close = frame["close"].to_numpy(dtype=float)
        raw_close = close.copy()
        if symbol in later:
            days, factor = later[symbol]
            raw_close *= factor[np.searchsorted(days, frame["stamp"].to_numpy("datetime64[D]"), side="right")]
        if not ((raw_close >= STARTING.price_min) & (raw_close <= STARTING.price_max)).any():
            continue
        out[str(symbol)] = Series(
            days=tuple(frame["stamp"].dt.date), open=frame["open"].to_numpy(dtype=float),
            high=frame["high"].to_numpy(dtype=float), low=frame["low"].to_numpy(dtype=float), close=close,
            volume=frame["volume"].to_numpy(dtype=float), raw_close=raw_close,
        )
    return out


def _later_splits(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """The split days, and factor[k] = the product of the ratios from the k-th split on (1 after the last)."""
    ratios = frame["split"].to_numpy(dtype=float)
    factor = np.append(np.cumprod(ratios[::-1])[::-1], 1.0)
    return frame["stamp"].to_numpy("datetime64[D]"), factor


def sessions_of(prices: pd.DataFrame) -> list[date]:
    """Every day any symbol traded, ascending."""
    return sorted(pd.to_datetime(prices["day"].drop_duplicates()).dt.date)


def _signals(symbol: str, s: Series, rule: Rule) -> tuple[np.ndarray, int]:
    """The sessions that signal, and how many sessions were skipped as split-suspects."""
    cache = _found.get()
    key = (symbol, *(getattr(rule, name) for name in IGNITION_FIELDS))
    if cache is not None and key in cache:
        return cache[key]
    found = ignitions(s, rule)
    got = (np.flatnonzero(found.signal), int(found.split_suspect.sum()))
    if cache is not None:
        cache[key] = got
    return got


def _trade(s: Series, i: int, sessions: Sequence[date], rule: Rule) -> dict | None:
    """The signal on session i, settled as live does. None when it is incomplete or live would not store it."""
    if i + 1 >= len(s.days):
        return None
    entry_day, entry = s.days[i + 1], float(s.open[i + 1])
    last = bisect_left(sessions, entry_day) + rule.hold_sessions - 1  # the entry day is day 1
    if last >= len(sessions):
        return None
    hold_by = sessions[last]
    signal_close, signal_low = float(s.close[i]), float(s.low[i])
    if plan_for(signal_close, signal_low, hold_by, rule) is None:  # live stores no signal without a stop under D's close
        return None
    row = {"signal_day": s.days[i], "entry_day": entry_day, "skip_reason": None, "gross_r": None, "cost_r": None, "net_r": None}
    if gapped(signal_close, entry, rule):
        return row | {"status": "skipped", "skip_reason": GAPPED}
    plan = plan_for(entry, signal_low, hold_by, rule)
    if plan is None:
        return row | {"status": "skipped", "skip_reason": "opened under the stop"}
    end = min(len(s.days), bisect_left(s.days, hold_by) + 1)  # settling stops at the first bar on or after the hold-by
    outcome = settle(s.bars(i + 1, end), plan)
    if outcome.status == "open":  # its bars end before the hold-by
        return None
    cost = cost_r(spread_pct(s, i), entry, plan.stop)
    return row | {"status": outcome.status, "gross_r": outcome.gross_r, "cost_r": cost, "net_r": outcome.gross_r - cost}


def trades(series: Mapping[str, Series], sessions: Sequence[date], rule: Rule) -> pd.DataFrame:
    """One row per signal. Split-suspects are not rows; their count is in `attrs["split_suspect"]`.

    A signal with no bar after D, or whose hold-by is past the last session, is dropped, and so is a
    trade still open at the end of the data.
    """
    rows, suspect = [], 0
    for symbol, s in series.items():
        found, suspects = _signals(symbol, s, rule)
        suspect += suspects
        for i in found:
            row = _trade(s, int(i), sessions, rule)
            if row is not None:
                rows.append({"symbol": symbol, **row})
    out = pd.DataFrame(rows, columns=COLUMNS)
    out.attrs["split_suspect"] = suspect
    return out


def variants(base: Rule) -> list[tuple[str, Rule]]:
    return [("starting values", base), *((name, replace(base, **{field: value})) for name, field, value in CHANGES)]


def report(rows: pd.DataFrame) -> dict:
    """Counts and R for the trades. Skipped rows are not trades; averages are None with no trades."""
    skipped = rows[rows["status"] == "skipped"]
    done = rows[rows["status"] != "skipped"]
    net = done["net_r"].astype(float)
    gaps = int((skipped["skip_reason"] == GAPPED).sum())
    any_trades = len(done) > 0
    worst = done.assign(net_r=net).sort_values("net_r", kind="stable").head(WORST)
    return {
        "signals": len(done),
        "skipped_gap": gaps,
        "skipped_other": len(skipped) - gaps,
        **{status: int((done["status"] == status).sum()) for status in ("target", "stop", "held")},
        "avg_net_r": float(net.mean()) if any_trades else None,
        "median_net_r": float(net.median()) if any_trades else None,
        "lost_over_1r": float((done["gross_r"].astype(float) < -1).mean()) if any_trades else None,
        "worst": [
            {"symbol": str(row.symbol), "signal_day": row.signal_day.isoformat(), "net_r": float(row.net_r)}
            for row in worst.itertuples()
        ],
    }


def cutoff_of(sessions: Sequence[date]) -> date:
    """The first session of the newest third."""
    return sessions[2 * len(sessions) // 3]


def run_backtest(series: Mapping[str, Series], sessions: Sequence[date], frozen: Rule | None) -> dict:
    """Try every variant; pick the best older average among those with enough older trades.

    The newer third is reported, never read to choose. `frozen` is the rule live runs now.
    """
    cutoff = cutoff_of(sessions)

    def halves(rows: pd.DataFrame) -> tuple[dict, dict]:
        older = rows["signal_day"] < cutoff
        return report(rows[older]), report(rows[~older])

    token = _found.set({})
    try:
        tried = [(name, rule, trades(series, sessions, rule)) for name, rule in variants(STARTING)]
        frozen_rows = None if frozen is None else trades(series, sessions, frozen)
    finally:
        _found.reset(token)

    judged = [(name, rule, rows, *halves(rows)) for name, rule, rows in tried]
    enough = [v for v in judged if v[3]["signals"] >= MIN_TO_CHOOSE]
    if enough:
        name, rule, rows, older, newer = max(enough, key=lambda v: v[3]["avg_net_r"])  # ties: the first
        note = None
    else:
        name, rule, rows, older, newer = judged[0]
        note = "too few signals to choose"
    frozen_report = None
    if frozen is not None:
        frozen_older, frozen_newer = halves(frozen_rows)
        frozen_report = {"settings": frozen.settings(), "older": frozen_older, "newer": frozen_newer}
    return {
        "data_from": sessions[0].isoformat(),
        "data_to": sessions[-1].isoformat(),
        "cutoff": cutoff.isoformat(),
        "variants_tried": len(tried),
        "pick": {"name": name, "settings": rule.settings(), "older": older, "newer": newer, "note": note},
        "frozen": frozen_report,
        "split_suspect": int(rows.attrs.get("split_suspect", 0)),
    }
