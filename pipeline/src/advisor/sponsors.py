"""Matching company names in catalyst data to the run's stocks.

Drug sponsors, recalling firms and trial sponsors are names, not tickers, and they come in
several forms for one company:
- FDA shorthand: "MERCK SHARP DOHME", "JANSSEN PHARMS", "ELI LILLY AND CO";
- legal names: "Vertex Pharmaceuticals Incorporated";
- subsidiaries: "Seagen, a wholly owned subsidiary of Pfizer", "Kite, A Gilead Company",
  "MSD SUB MERCK".

Each name is reduced to a key: its parent company, first comma part, upper case, abbreviations
spelled out, and legal words dropped. A name matches a stock when the keys are equal, or when
one key starts with the other ("NOVARTIS PHARMACEUTICALS" -> Novartis). A name matching two
different companies matches none.

Only the run's stocks are matched (a few hundred names, not 13,000), which keeps collisions
rare. ALIASES covers subsidiaries and old names the rules can't reach. A one-word key that is
also an everyday word ("UNITED", "AMERICAN") matches only exactly. NOT_THE_STOCK lists the few
companies that share a stock's name (Merck KGaA).
"""

import re
from collections import defaultdict
from collections.abc import Mapping

from advisor.company_names import search_name
from advisor.news.mapping import COMMON_WORDS

# A subsidiary named with its parent: the parent is the company.
PARENT = (
    re.compile(r",?\s+an?\s+(?:wholly[- ]owned\s+)?subsidiary\s+of\s+(.+)$", re.IGNORECASE),
    re.compile(r",?\s+an?\s+(.+?)\s+company$", re.IGNORECASE),
    re.compile(r"^\S+\s+SUB\s+(.+)$"),  # FDA's "MSD SUB MERCK"
)
PARENTHETICAL = re.compile(r"\([^()]*\)")
ABBREVIATIONS = {
    "PHARM": "PHARMACEUTICALS", "PHARMS": "PHARMACEUTICALS", "PHARMACEUTICAL": "PHARMACEUTICALS",
    "THERAP": "THERAPEUTICS", "HLTHCARE": "HEALTHCARE", "BIOSCI": "BIOSCIENCES",
    "ONCOL": "ONCOLOGY", "LAB": "LABORATORIES", "LABS": "LABORATORIES", "INDS": "INDUSTRIES",
    "INTL": "INTERNATIONAL",
}
LEGAL = frozenset({
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "COMPANIES", "LTD", "LIMITED",
    "LLC", "LP", "PLC", "SA", "AG", "SE", "NV", "BV", "GMBH", "HOLDINGS", "HOLDING", "GROUP",
    "AB", "ASA", "SPA", "PTE", "PTY", "USA", "US", "AND", "THE",
})
COMMON = frozenset(word.upper() for word in COMMON_WORDS)
# Names the rules can't reach, as keys: the stock they belong to. Used only when that stock is
# in the run. Subsidiaries of companies outside both universes (Genentech -> Roche) aren't here.
ALIASES = {
    "MERCK SHARP DOHME": "MRK",
    "MSD": "MRK",
    "MSD MERCK": "MRK",
    "JANSSEN": "JNJ",
    "ABIOMED": "JNJ",
    "BRISTOL": "BMY",
    "GLAXOSMITHKLINE": "GSK",
    "VIIV HEALTHCARE": "GSK",
    "LOXO ONCOLOGY": "LLY",
    "IMMUNEX": "AMGN",
    "MODERNATX": "MRNA",
    "HOWMEDICA OSTEONICS": "SYK",
    "BAUSCH HEALTH AMERICAS": "BHC",
    "BAXTER": "BAX",  # Baxter Healthcare
    "TEVA": "TEVA",  # Teva Branded Pharmaceutical Products, Teva Pharmaceuticals USA
    "MYLAN": "VTRS",
}

# Companies whose names start with a stock's name but are another company: they match nothing.
NOT_THE_STOCK = ("MERCK KGAA",)  # Merck KGaA of Darmstadt (EMD Serono) isn't Merck & Co.


def company_key(name: str) -> str:
    """'Seagen, a wholly owned subsidiary of Pfizer' -> 'PFIZER'; 'JANSSEN PHARMS' -> 'JANSSEN PHARMACEUTICALS'."""
    name = name.strip()
    for pattern in PARENT:
        if match := pattern.search(name):
            name = match.group(1)
            break
    name = PARENTHETICAL.sub(" ", name).split(",")[0].upper()
    name = name.replace("A/S", " ").replace("&", " AND ").replace(".", "").replace("'", "")
    words = [ABBREVIATIONS.get(word, word) for word in re.split(r"[^A-Z0-9]+", name) if word]
    while words and words[-1] in LEGAL:
        words.pop()
    while words and words[0] == "THE":
        words.pop(0)
    return " ".join(words)


def _extends(longer: str, shorter: str) -> bool:
    return longer.startswith(shorter + " ") and shorter not in COMMON


class SponsorMatcher:
    def __init__(self, names: Mapping[str, str], aliases: Mapping[str, str] = ALIASES) -> None:
        """`names`: the run's stocks, symbol -> directory name ("Pfizer, Inc. Common Stock")."""
        self._symbols: dict[str, set[str]] = defaultdict(set)
        for symbol, directory_name in names.items():
            if key := company_key(search_name(directory_name)):
                self._symbols[key].add(symbol)
        for alias, symbol in aliases.items():
            if symbol in names:
                self._symbols[company_key(alias)].add(symbol)
        self._by_first_word: dict[str, list[str]] = defaultdict(list)
        for key in self._symbols:
            self._by_first_word[key.split()[0]].append(key)

    def symbols_for(self, name: str) -> set[str]:
        """The run's stocks this company name belongs to; none when unknown or ambiguous."""
        key = company_key(name)
        if not key or any(key == other or key.startswith(other + " ") for other in NOT_THE_STOCK):
            return set()
        if key in self._symbols:
            return set(self._symbols[key])
        nearby = self._by_first_word.get(key.split()[0], [])
        matches = [k for k in nearby if _extends(key, k) or _extends(k, key)]
        companies = {frozenset(self._symbols[k]) for k in matches}
        return set(next(iter(companies))) if len(companies) == 1 else set()
