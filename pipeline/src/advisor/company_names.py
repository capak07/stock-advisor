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

# What follows the company in a directory name: NASDAQ's " - Common Stock"; NYSE's " Class B Common
# Stock", " New Common Stock", " Class A Sub. Vot. Common Stock", " Class A Limited Voting Shares",
# " Limited Partnership Units", " American Depositary Shares, each representing ...", " Sponsored
# ADR", " Class B"; trusts' " Units of Beneficial Interest" (checked against the full NASDAQ
# Trader and TMX directories, 2026-10-16). A word that only looks like one stays: "China A Share
# Fund", "World Class Holdings".
CLASS = r"Class\s+[A-Z](?:-\d+)?"
INSTRUMENT = re.compile(
    r"\s+(?:-\s+.*"
    rf"|(?:New\s+)?(?:{CLASS}\s+)?(?i:common|ordinary|sub(?:ordinate)?\.?\s+vot(?:ing)?"
    r"|limited voting|exchangeable|voting|representing|american deposit[ao]ry|deposit[ao]ry"
    r"|limited partnership|(?:new york|ny) registry|(?:spon\w*\s+)?adrs?)\b.*"
    rf"|(?:{CLASS}\s+)?(?i:shares?|units?)(?:\s+(?i:of|representing)\b.*|,.*)?"
    rf"|{CLASS}"
    r"|ADS\b.*"  # upper case only: "SAP SE ADS", not "Digital Ads"
    r")$"
)
PARENTHETICAL = re.compile(r"\s*\([^()]*\)")  # "(The)", "(REIT)", "(New)", "(representing ...)"
TRAILING_NEW = re.compile(r"\s+New$")  # "Central Pacific Financial Corp New"
LEGAL = re.compile(
    r"(?:,?\s+&?\s*(?:Inc|Incorporated|Corp|Corporation|Co|Company|Ltd|Limited|plc|PLC|LLC"
    r"|L\.P|LP|N\.V|S\.A|SA|SE|AG|Holdings?|Group)\.?)+$"
)


def search_name(directory_name: str) -> str:
    """'Apple Inc. - Common Stock' -> 'Apple Inc'. TMX names, such as 'Royal Bank of Canada', are unchanged.

    Parenthetical notes go first, innermost first ("(each representing twenty (20) ...)"); NASDAQ
    and NYSE put "The" last as one: "Walt Disney Company (The)".
    """
    name = directory_name
    while (bare := PARENTHETICAL.sub(" ", name)) != name:
        name = bare
    name = " ".join(name.split()).replace(" ,", ",")  # "Jerash Holdings (US), Inc"
    name = INSTRUMENT.sub("", name).strip().rstrip(".")
    return TRAILING_NEW.sub("", name).strip().rstrip(".").strip()


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
