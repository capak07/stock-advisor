"""Every collector the pipeline runs, keyed by name, with one rate limiter per provider."""

import httpx

from advisor.collectors.base import Collector, RateLimiter
from advisor.collectors.blockchain_stats import BLOCKCHAIN_PER_MINUTE, BlockchainStats
from advisor.collectors.boc_valet import BankOfCanadaValet
from advisor.collectors.cnn_fear_greed import CnnFearGreed
from advisor.collectors.coinbase_candles import COINBASE_PER_MINUTE, CoinbaseCandles
from advisor.collectors.coingecko import COINGECKO_PER_MINUTE, CoinGecko
from advisor.collectors.crypto_fear_greed import CryptoFearGreed
from advisor.collectors.defillama_tvl import DEFILLAMA_PER_MINUTE, DefiLlamaTvl
from advisor.collectors.finra_short_interest import FinraShortInterest
from advisor.collectors.finra_short_volume import FinraShortVolume
from advisor.collectors.fomc import Fomc
from advisor.collectors.fred import FRED_PER_MINUTE, Fred
from advisor.collectors.google_news import GOOGLE_NEWS_PER_MINUTE, GoogleNews
from advisor.collectors.kraken_ohlc import KRAKEN_PER_MINUTE, KrakenOhlc
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.news_feeds import FEED_PER_MINUTE, FEEDS, FeedNews
from advisor.collectors.openfigi import OPENFIGI_PER_MINUTE, FigiBook
from advisor.collectors.sec import SEC_PER_MINUTE, SecEdgar
from advisor.collectors.sec_13f import Sec13f
from advisor.collectors.sec_events import SecEvents
from advisor.collectors.sec_holders import SecHolders
from advisor.collectors.sec_insiders import SecInsiders
from advisor.collectors.sec_xbrl import SecXbrl
from advisor.collectors.tmx_symbols import TmxSymbols
from advisor.collectors.yahoo import YAHOO_PER_MINUTE
from advisor.collectors.yahoo_news import YAHOO_NEWS_PER_MINUTE, YahooNews
from advisor.collectors.yfinance_analyst import YFinanceAnalyst
from advisor.collectors.yfinance_bars import YFinanceBars
from advisor.collectors.yfinance_earnings import YFinanceEarnings
from advisor.collectors.yfinance_options import YFinanceOptions
from advisor.company_names import CompanyNames
from advisor.config import Settings

FINRA_PER_MINUTE = 60


def build_registry(
    settings: Settings, client: httpx.Client, *, names: CompanyNames | None = None
) -> dict[str, Collector]:
    """`names` is filled by the run once the universes are loaded; Google News queries by them."""
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
        YFinanceOptions(limiter=yahoo),
        BankOfCanadaValet(client),
        SecXbrl(sec),
        SecEvents(sec),
        SecInsiders(sec),
        SecHolders(sec),
        Sec13f(
            sec,
            FigiBook(
                client,
                settings.cache_dir / "sec-13f" / "figis.json",
                RateLimiter(per_minute=OPENFIGI_PER_MINUTE),
            ),
            settings.cache_dir / "sec-13f",
        ),
        Fred(client, RateLimiter(per_minute=FRED_PER_MINUTE, burst=3)),
        Fomc(client),
        CnnFearGreed(client),
        CryptoFearGreed(client),
        BlockchainStats(client, RateLimiter(per_minute=BLOCKCHAIN_PER_MINUTE, burst=1)),
        DefiLlamaTvl(client, RateLimiter(per_minute=DEFILLAMA_PER_MINUTE, burst=2)),
        CoinGecko(client, RateLimiter(per_minute=COINGECKO_PER_MINUTE, burst=1)),
        CoinbaseCandles(client, RateLimiter(per_minute=COINBASE_PER_MINUTE, burst=3)),
        KrakenOhlc(client, RateLimiter(per_minute=KRAKEN_PER_MINUTE, burst=1)),
        YahooNews(client, RateLimiter(per_minute=YAHOO_NEWS_PER_MINUTE, burst=2)),
        GoogleNews(client, RateLimiter(per_minute=GOOGLE_NEWS_PER_MINUTE, burst=1), names=names),
        *(FeedNews(feed, client, RateLimiter(per_minute=FEED_PER_MINUTE, burst=2)) for feed in FEEDS),
    ]
    return {collector.name: collector for collector in collectors}
