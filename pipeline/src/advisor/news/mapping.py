"""Which stocks and coins a market-wide news item is about (spec §4.3 stage 5).

Evidence, strongest first:
1. the tickers a feed names (Nasdaq's `<nasdaq:tickers>`). A roundup naming more than 8 counts for
   none of them.
2. exchange tags in the title or summary: "(NYSE: CNC)", "NASDAQ:AAPL", "(TSX: BBD.B)". TSX
   Venture and CSE tickers are outside the universe.
3. cashtags: "$AAPL", "$BTC".
4. names in the title. Every stock in both universes contributes its short name ("Apple",
   "Royal Bank of Canada") and each held or watched coin its name ("Bitcoin"). The longest name
   wins where names overlap, so a headline about Apple Hospitality is not read as Apple. Share
   classes share a name, so "Alphabet" counts for both GOOG and GOOGL. A one-word name that is also
   an everyday word ("Target", "Gap", "Stellar") counts only through tags or cashtags.

Only targets (held, watched and shortlisted assets) are reported.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping

from advisor.collectors.feeds import NewsItem
from advisor.company_names import short_name
from advisor.markets import TSX_SUFFIX
from advisor.models import AssetRef, AssetType

MAX_TAGS = 8
LONGEST_NAME = 6  # words
EXCHANGE_TAG = re.compile(
    r"\b(NYSE American|NYSE Arca|NYSE|NASDAQ|Nasdaq|TSX|TSXV|TSX-V|CSE)\s*:\s*"
    r"([A-Z][A-Z0-9]*(?:\.[A-Z]{1,2})?)\b"
)
CASHTAG = re.compile(r"(?<![\w$])\$([A-Z]{1,6}(?:\.[A-Z])?)\b")
WORD = re.compile(r"[A-Za-z0-9&]+(?:['’.\-][A-Za-z0-9&]+)*")
US_EXCHANGES = frozenset({"NYSE American", "NYSE Arca", "NYSE", "NASDAQ", "Nasdaq"})
# One-word company names that are also everyday words: tags and cashtags only.
COMMON_WORDS = frozenset({
    "Advance", "Alliance", "American", "Applied", "Avalanche", "Ball", "Bank", "Best", "Block",
    "Bright", "Capital", "Carrier", "Central", "Citizens", "Clear", "Compass", "Core", "Cosmos",
    "Crown", "Dash", "Delta", "Dollar", "Eagle", "Element", "Energy", "Equity", "Evolution", "First",
    "Flare", "Flow", "Frontier", "Gap", "Gas", "General", "Global", "Gold", "Guardian", "Harmony",
    "Helium", "Heritage", "Home", "Hope", "Immutable", "Insight", "Jupiter", "Liberty", "Maker",
    "Mantle", "Match", "Nasdaq", "National", "Nature", "New", "Northern", "Optimism", "Pacific",
    "Pioneer", "Polygon", "Power", "Premier", "Progressive", "Prosperity", "Quality", "Quant",
    "Regions", "Reliance", "Render", "Republic", "Royal", "Shell", "Sigma", "Snap", "Sonic",
    "Southern", "Stacks", "Stellar", "Sun", "Target", "Terra", "Total", "Trade", "Travelers",
    "Trust", "Union", "United", "Unity", "Universal", "Value", "Visa", "Western",
})
# Names that start with a coin's name but are another coin; they match nothing unless held.
NOT_COINS = ("Bitcoin Cash", "Bitcoin Gold", "Bitcoin SV", "Ethereum Classic")
# "Morgan Stanley Upgrades Tesla to Overweight": the broker is not what the item is about.
ANALYST_VERBS = frozenset({
    "upgrades", "downgrades", "raises", "lowers", "cuts", "lifts", "boosts", "trims", "hikes",
    "initiates", "reiterates", "maintains", "starts", "resumes", "reinstates",
})
RATING = re.compile(
    r"\b(?:target|rating|overweight|underweight|equal[- ]weight|outperform|underperform"
    r"|market perform|sector perform|buy|sell|neutral|hold|coverage)\b",
    re.IGNORECASE,
)


def tsx_symbol(ticker: str) -> str:
    """'BBD.B' as written in a press release -> 'BBD-B.TO', the form the app uses."""
    return ticker.replace(".", "-") + TSX_SUFFIX


def words(text: str) -> list[str]:
    """The words of a title, with possessives dropped ("Apple's" -> "Apple")."""
    return [word.removesuffix("'s").removesuffix("’s") for word in WORD.findall(text)]


class TickerMap:
    def __init__(
        self,
        stock_names: Mapping[str, str],  # every stock of both universes: symbol -> directory name
        coin_names: Mapping[str, str],  # held and watched coins: symbol -> name
        targets: Iterable[AssetRef],
    ) -> None:
        self._targets = frozenset(targets)
        self._names: dict[tuple[str, ...], set[AssetRef]] = defaultdict(set)
        for symbol, directory_name in stock_names.items():
            self._add(short_name(directory_name), AssetRef(symbol, AssetType.STOCK))
        for symbol, name in coin_names.items():
            self._add(name, AssetRef(symbol, AssetType.CRYPTO))
        for name in NOT_COINS:
            self._names.setdefault(tuple(words(name)), set())

    def _add(self, name: str, ref: AssetRef) -> None:
        key = tuple(words(name))
        if key and len(key) <= LONGEST_NAME and not (len(key) == 1 and key[0] in COMMON_WORDS):
            self._names[key].add(ref)

    def assets_in(self, item: NewsItem) -> set[AssetRef]:
        """The targets an item names, by any of the four kinds of evidence."""
        found: set[AssetRef] = set()
        if len(item.tags) <= MAX_TAGS:
            found |= {AssetRef(tag, AssetType.STOCK) for tag in item.tags}
        text = f"{item.title} {item.summary}"
        for exchange, ticker in EXCHANGE_TAG.findall(text):
            if exchange in US_EXCHANGES:
                found.add(AssetRef(ticker, AssetType.STOCK))
            elif exchange == "TSX":
                found.add(AssetRef(tsx_symbol(ticker), AssetType.STOCK))
        for ticker in CASHTAG.findall(text):
            found |= {AssetRef(ticker, AssetType.STOCK), AssetRef(ticker, AssetType.CRYPTO)}
        found |= self._named(item.title)
        return found & self._targets

    def _named(self, title: str) -> set[AssetRef]:
        """Names in the title, longest first at each position, scanning left to right."""
        tokens = words(title)
        matches: list[tuple[set[AssetRef], str]] = []  # each name's assets and the word after it
        start = 0
        while start < len(tokens):
            for size in range(min(LONGEST_NAME, len(tokens) - start), 0, -1):
                refs = self._names.get(tuple(tokens[start:start + size]))
                if refs is not None:
                    after = tokens[start + size] if start + size < len(tokens) else ""
                    matches.append((refs, after.lower()))
                    start += size
                    break
            else:
                start += 1
        if RATING.search(title) and sum(1 for refs, _ in matches if refs) > 1:
            matches = [(refs, after) for refs, after in matches if after not in ANALYST_VERBS]
        return set().union(*(refs for refs, _ in matches))
