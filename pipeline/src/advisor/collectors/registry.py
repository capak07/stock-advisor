"""Every collector the pipeline runs, keyed by name. Later plans add the remaining sources here."""

import httpx

from advisor.collectors.base import Collector
from advisor.collectors.nasdaq_symbols import NasdaqSymbols
from advisor.collectors.yfinance_bars import YFinanceBars
from advisor.config import Settings


def build_registry(settings: Settings, client: httpx.Client) -> dict[str, Collector]:
    collectors: list[Collector] = [NasdaqSymbols(client), YFinanceBars()]
    return {collector.name: collector for collector in collectors}
