"""Company names for news: the phrase Google News is searched for, and the name headlines use.

Names come from the stock directories the run loads before enrichment:
- NASDAQ Trader, e.g. "Apple Inc. - Common Stock";
- TMX, e.g. "Royal Bank of Canada".

A stock with no known name (an OTC holding, or the daily health check, which loads no directory) is
searched by ticker.
"""

import re
import threading
from collections.abc import Mapping

# What follows the company in a directory name: NASDAQ's " - Common Stock", and NYSE's
# " Class B Common Stock", " Common Units representing ...", " American Depositary Shares".
INSTRUMENT = re.compile(
    r"\s+(?:-\s+.*|(?:Class\s+[A-Z]\s+)?"
    r"(?:Common|Ordinary|Subordinate Voting|American Depositary|Depositary)\b.*)$"
)
LEGAL = re.compile(
    r"(?:,?\s+&?\s*(?:Inc|Incorporated|Corp|Corporation|Co|Company|Ltd|Limited|plc|PLC|LLC"
    r"|L\.P|LP|N\.V|S\.A|SA|SE|AG|Holdings?|Group)\.?)+$"
)


def search_name(directory_name: str) -> str:
    """'Apple Inc. - Common Stock' -> 'Apple Inc'. TMX names, such as 'Royal Bank of Canada', are unchanged."""
    return INSTRUMENT.sub("", directory_name).strip().rstrip(".").strip()


def short_name(directory_name: str) -> str:
    """The name headlines use: 'United Airlines Holdings, Inc. - Common Stock' -> 'United Airlines'."""
    return LEGAL.sub("", search_name(directory_name)).strip(" ,.&").removeprefix("The ")


class CompanyNames:
    """Directory names by symbol. The run fills them once the universes are loaded."""

    def __init__(self, names: Mapping[str, str] | None = None) -> None:
        self._names = dict(names or {})
        self._lock = threading.Lock()

    def update(self, names: Mapping[str, str]) -> None:
        with self._lock:
            self._names.update(names)

    def get(self, symbol: str) -> str | None:
        with self._lock:
            return self._names.get(symbol)

    def items(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._names.items())
