"""Every collector the pipeline runs, keyed by name. Plan 2 adds the remaining sources here."""

import httpx

from advisor.collectors.alpaca_bars import AlpacaBars
from advisor.collectors.base import Collector
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.yfinance_bars import YFinanceBars
from advisor.config import Settings


def build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]:
    collectors: list[Collector] = [
        NasdaqSymbols(client),
        AlpacaBars(client, settings.alpaca_key_id, settings.alpaca_secret_key),
        YFinanceBars(),
    ]
    return {collector.name: collector for collector in collectors}
