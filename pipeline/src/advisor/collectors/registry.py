"""Every collector the pipeline runs, keyed by name, with one rate limiter per provider."""

import httpx

from advisor.collectors.base import Collector, RateLimiter
from advisor.collectors.boc_valet import BankOfCanadaValet
from advisor.collectors.finra_short_interest import FinraShortInterest
from advisor.collectors.finra_short_volume import FinraShortVolume
from advisor.collectors.fomc import Fomc
from advisor.collectors.fred import FRED_PER_MINUTE, Fred
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.sec import SEC_PER_MINUTE, SecEdgar
from advisor.collectors.sec_events import SecEvents
from advisor.collectors.sec_holders import SecHolders
from advisor.collectors.sec_insiders import SecInsiders
from advisor.collectors.sec_xbrl import SecXbrl
from advisor.collectors.tmx_symbols import TmxSymbols
from advisor.collectors.yahoo import YAHOO_PER_MINUTE
from advisor.collectors.yfinance_analyst import YFinanceAnalyst
from advisor.collectors.yfinance_bars import YFinanceBars
from advisor.collectors.yfinance_earnings import YFinanceEarnings
from advisor.config import Settings

FINRA_PER_MINUTE = 60


def build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]:
    finra = RateLimiter(per_minute=FINRA_PER_MINUTE, burst=2)  # shared by FINRA's collectors
    yahoo = RateLimiter(per_minute=YAHOO_PER_MINUTE, burst=2)  # shared by Yahoo's per-symbol collectors
    sec = SecEdgar(  # shared by every SEC collector
        client,
        settings.sec_user_agent,
        RateLimiter(per_minute=SEC_PER_MINUTE, burst=5),
        documents=settings.cache_dir / "sec-documents",
    )
    collectors: list[Collector] = [
        NasdaqSymbols(client),
        TmxSymbols(client),
        YFinanceBars(),
        FinraShortVolume(client, finra),
        FinraShortInterest(client, finra),
        YFinanceAnalyst(limiter=yahoo),
        YFinanceEarnings(limiter=yahoo),
        BankOfCanadaValet(client),
        SecXbrl(sec),
        SecEvents(sec),
        SecInsiders(sec),
        SecHolders(sec),
        Fred(client, RateLimiter(per_minute=FRED_PER_MINUTE, burst=3)),
        Fomc(client),
    ]
    return {collector.name: collector for collector in collectors}
