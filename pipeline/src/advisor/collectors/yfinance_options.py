"""Option-market summaries per US stock from Yahoo option chains via yfinance (source 18).

Yahoo answers one expiry per request. The first request also lists every expiry and returns the
nearest chain, often expiring today (0DTE). Then two more requests fetch:
- the "near" expiry, the first at least NEAR_DAYS away;
- the "mid" expiry, the one closest to MID_DAYS out of those at least MID_MIN_DAYS away.

From those chains the record keeps:
- at-the-money implied volatility (IV) per expiry;
- a put/call skew;
- put/call volume and open-interest ratios. Chains expiring today are left out: they dominate the
  day's volume.

IV is live during the session, and volume counts the day so far, so a record describes the
market at `quote_time`. A quote without a bid and an ask, or with Yahoo's 1e-05 IV placeholder,
is not used.

TSX stocks have no options on Yahoo, so the source is US only. A stock without options yields no
record, like the other Yahoo sources. The source is capped per call to the top of the shortlist.
"""

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from advisor.collectors.base import Cadence, Category, RateLimiter, Scope
from advisor.collectors.yahoo import collect_yahoo
from advisor.collectors.yfinance_bars import to_yahoo
from advisor.models import ET, AssetType, Market

NEAR_DAYS = 7
MID_DAYS = 30
MID_MIN_DAYS = 21
MIN_IV = 0.01  # below this Yahoo is showing its 1e-05 placeholder, not a quote
SKEW_PUT = 0.95  # skew compares the put 5% below spot with the call 5% above
SKEW_CALL = 1.05
SKEW_TOLERANCE = 0.03  # the nearest quoted strike must be within 3% of spot of the target


@dataclass(frozen=True)
class Chain:
    expiry: date
    calls: pd.DataFrame
    puts: pd.DataFrame


@dataclass(frozen=True)
class ChainSet:
    quote: dict  # Yahoo's quote of the underlying, from the same responses
    expiries: list[date]
    chains: list[Chain]


Chooser = Callable[[list[date]], list[date]]
Loader = Callable[[str, Chooser], ChainSet | None]  # None: the stock has no listed options


class OptionsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: date  # ET date of the run
    quote_time: datetime | None = None  # when Yahoo last priced the underlying (UTC)
    market_state: str | None = None  # Yahoo's "REGULAR", "PRE", "POST", "CLOSED"...
    underlying_price: float | None = None
    expiries: int  # listed expiries
    near_expiry: date | None = None
    atm_iv_near: float | None = None  # a fraction: 0.24 is 24%
    mid_expiry: date | None = None
    atm_iv_mid: float | None = None
    skew_near: float | None = None  # IV of the 95% put minus IV of the 105% call, near expiry
    call_volume: int = 0  # over the fetched chains, leaving out any expiring today
    put_volume: int = 0
    call_open_interest: int = 0
    put_open_interest: int = 0
    put_call_volume: float | None = None
    put_call_open_interest: float | None = None


def choose_expiries(expiries: Sequence[date], today: date) -> list[date]:
    """The near expiry and the mid expiry (when they exist), deduplicated, in date order."""
    near = next((e for e in sorted(expiries) if (e - today).days >= NEAR_DAYS), None)
    later = [e for e in expiries if (e - today).days >= MID_MIN_DAYS]
    mid = min(later, key=lambda e: (abs((e - today).days - MID_DAYS), e)) if later else None
    return sorted({e for e in (near, mid) if e is not None})


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def quoted(side: pd.DataFrame) -> pd.DataFrame:
    """The contracts with a live two-sided quote and a real IV."""
    if side is None or side.empty:
        return pd.DataFrame(columns=["strike", "impliedVolatility"])
    frame = side.reindex(columns=["strike", "bid", "ask", "impliedVolatility"])
    frame = frame.apply(pd.to_numeric, errors="coerce")
    keep = (frame["bid"] > 0) & (frame["ask"] > 0) & (frame["impliedVolatility"] > MIN_IV)
    return frame[keep]


def atm_iv(chain: Chain, spot: float) -> float | None:
    """IV at the spot price: the strikes either side of spot, calls and puts averaged, interpolated."""
    both = pd.concat([quoted(chain.calls), quoted(chain.puts)])
    if both.empty:
        return None
    by_strike = both.groupby("strike")["impliedVolatility"].mean().sort_index()
    below = by_strike[by_strike.index <= spot]
    above = by_strike[by_strike.index >= spot]
    if below.empty or above.empty:
        return None
    low, high = float(below.index[-1]), float(above.index[0])
    if low == high:
        return float(below.iloc[-1])
    weight = (spot - low) / (high - low)
    return float(below.iloc[-1] + weight * (above.iloc[0] - below.iloc[-1]))


def _iv_near(side: pd.DataFrame, target: float, spot: float) -> float | None:
    live = quoted(side)
    if live.empty:
        return None
    distance = (live["strike"] - target).abs()
    nearest = live.loc[distance.idxmin()]
    if abs(nearest["strike"] - target) > SKEW_TOLERANCE * spot:
        return None
    return float(nearest["impliedVolatility"])


def skew(chain: Chain, spot: float) -> float | None:
    put = _iv_near(chain.puts, SKEW_PUT * spot, spot)
    call = _iv_near(chain.calls, SKEW_CALL * spot, spot)
    return None if put is None or call is None else put - call


def _total(side: pd.DataFrame, column: str) -> int:
    if side is None or side.empty or column not in side:
        return 0
    return int(pd.to_numeric(side[column], errors="coerce").fillna(0).sum())


def _ratio(puts: int, calls: int) -> float | None:
    return puts / calls if calls > 0 else None


def options_view(symbol: str, data: ChainSet, as_of: datetime) -> OptionsView | None:
    today = as_of.astimezone(ET).date()
    spot = _number(data.quote.get("regularMarketPrice"))
    if not data.expiries or spot is None or spot <= 0:
        return None
    chains = {chain.expiry: chain for chain in data.chains}
    wanted = choose_expiries(data.expiries, today)
    near = chains.get(wanted[0]) if wanted else None
    mid = chains.get(wanted[-1]) if len(wanted) > 1 else None
    counted = [chain for chain in data.chains if chain.expiry > today]  # not expiring today
    calls = _total_of(counted, "calls", "volume")
    puts = _total_of(counted, "puts", "volume")
    call_oi = _total_of(counted, "calls", "openInterest")
    put_oi = _total_of(counted, "puts", "openInterest")
    quote_time = _number(data.quote.get("regularMarketTime"))
    return OptionsView(
        symbol=symbol,
        as_of=today,
        quote_time=datetime.fromtimestamp(quote_time, UTC) if quote_time else None,
        market_state=data.quote.get("marketState"),
        underlying_price=spot,
        expiries=len(data.expiries),
        near_expiry=near.expiry if near else None,
        atm_iv_near=atm_iv(near, spot) if near else None,
        mid_expiry=mid.expiry if mid else None,
        atm_iv_mid=atm_iv(mid, spot) if mid else None,
        skew_near=skew(near, spot) if near else None,
        call_volume=calls,
        put_volume=puts,
        call_open_interest=call_oi,
        put_open_interest=put_oi,
        put_call_volume=_ratio(puts, calls),
        put_call_open_interest=_ratio(put_oi, call_oi),
    )


def _total_of(chains: Sequence[Chain], side: str, column: str) -> int:
    return sum(_total(getattr(chain, side), column) for chain in chains)


class YahooChains:
    """Loads chains through yfinance, taking a Yahoo limiter token before every request."""

    def __init__(self, limiter: RateLimiter | None = None) -> None:
        self._limiter = limiter

    def _request(self, read: Callable[[], Any]) -> Any:
        if self._limiter is not None:
            self._limiter.acquire()
        return read()

    def __call__(self, yahoo_symbol: str, choose: Chooser) -> ChainSet | None:
        import yfinance as yf  # imported lazily: slow import, and tests inject a fake

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        ticker = yf.Ticker(yahoo_symbol)
        first = self._request(ticker.option_chain)  # the expiry list and the nearest chain
        if first.calls is None:
            return None
        listed = list(ticker.options)  # from the first answer: no request
        expiries = [date.fromisoformat(text) for text in listed]
        chains = [Chain(expiries[0], first.calls, first.puts)]
        for expiry in choose(expiries):
            if expiry != expiries[0]:
                chain = self._request(partial(ticker.option_chain, expiry.isoformat()))
                chains.append(Chain(expiry, chain.calls, chain.puts))
        return ChainSet(first.underlying or {}, expiries, chains)


class YFinanceOptions:
    name = "yfinance_options"
    category = Category.OPTIONS
    core = False
    best_effort = True
    cadence = Cadence.PER_RUN
    asset_types = frozenset({AssetType.STOCK})
    markets = frozenset({Market.US})
    record_type = OptionsView
    freshness = timedelta(days=3)
    scope = Scope.SYMBOLS
    canary = ("AAPL",)
    canary_requires_records = True
    max_symbols = 40  # 3 requests each: about 120 Yahoo requests a run

    def __init__(self, load: Loader | None = None, limiter: RateLimiter | None = None) -> None:
        self._load = load or YahooChains(limiter)

    def fetch(self, symbols: Sequence[str], as_of: datetime) -> list[OptionsView]:
        today = as_of.astimezone(ET).date()

        def one(symbol: str) -> list[OptionsView]:
            data = self._load(to_yahoo(symbol), lambda expiries: choose_expiries(expiries, today))
            view = options_view(symbol, data, as_of) if data else None
            return [view] if view else []

        return collect_yahoo(symbols, one, limiter=None)  # the loader takes a token per request
