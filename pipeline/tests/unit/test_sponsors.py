import pytest

from advisor.sponsors import SponsorMatcher, company_key

# Directory names as NASDAQ Trader and TMX list them (2026-10-19)
NAMES = {
    "PFE": "Pfizer, Inc. Common Stock",
    "LLY": "Eli Lilly and Company Common Stock",
    "MRK": "Merck & Company, Inc. Common Stock (new)",
    "JNJ": "Johnson & Johnson Common Stock",
    "NVS": "Novartis AG Common Stock",
    "NVO": "Novo Nordisk A/S Common Stock",
    "AZN": "AstraZeneca PLC Ordinary Shares",
    "GILD": "Gilead Sciences, Inc. - Common Stock",
    "BMY": "Bristol-Myers Squibb Company Common Stock",
    "TAK": "Takeda Pharmaceutical Company Limited American Depositary Shares (each representing 1/2 of a share of Common Stock)",
    "MRNA": "Moderna, Inc. - Common Stock",
    "BHC": "Bausch Health Companies Inc. Common Stock",
    "UTHR": "United Therapeutics Corporation - Common Stock",
    "AIG": "American International Group, Inc. New Common Stock",
    "ACAD": "ACADIA Pharmaceuticals Inc. - Common Stock",
    "ACHC": "Acadia Healthcare Company, Inc. - Common Stock",
    "JAZZ": "Jazz Pharmaceuticals plc - Ordinary Shares",
    "GUD.TO": "Knight Therapeutics Inc.",
    "GOOG": "Alphabet Inc. - Class C Capital Stock",
    "GOOGL": "Alphabet Inc. - Class A Common Stock",
}


@pytest.mark.parametrize(("name", "key"), [
    ("ELI LILLY AND CO", "ELI LILLY"),
    ("Eli Lilly and Company", "ELI LILLY"),
    ("JANSSEN PHARMS", "JANSSEN PHARMACEUTICALS"),
    ("Seagen, a wholly owned subsidiary of Pfizer", "PFIZER"),
    ("Kite, A Gilead Company", "GILEAD"),
    ("Acceleron Pharma, Inc., a wholly-owned subsidiary of Merck & Co., Inc., Rahway, NJ USA", "MERCK"),
    ("MSD SUB MERCK", "MERCK"),
    ("Knight Therapeutics (USA) Inc", "KNIGHT THERAPEUTICS"),
    ("Hoffmann-La Roche", "HOFFMANN LA ROCHE"),
    ("Novo Nordisk A/S", "NOVO NORDISK"),
    ("ASTRAZENECA AB", "ASTRAZENECA"),
])
def test_a_company_key_is_the_parent_without_legal_words(name, key):
    assert company_key(name) == key


@pytest.mark.parametrize(("sponsor", "symbols"), [
    ("PFIZER", {"PFE"}),  # FDA's drug sponsor
    ("Pfizer", {"PFE"}),  # ClinicalTrials.gov's lead sponsor
    ("ELI LILLY AND CO", {"LLY"}),
    ("DICE Therapeutics, Inc., a wholly owned subsidiary of Eli Lilly and Company", {"LLY"}),
    ("NOVARTIS PHARMACEUTICALS CORP", {"NVS"}),  # starts with a stock's name
    ("Novo Nordisk A/S", {"NVO"}),
    ("ASTRAZENECA AB", {"AZN"}),
    ("TAKEDA PHARMS USA", {"TAK"}),
    ("JAZZ", {"JAZZ"}),  # FDA cuts names short: a stock's name starts with it
    ("Bristol-Myers Squibb", {"BMY"}),
    ("Karuna Therapeutics, Inc., a Bristol Myers Squibb company", {"BMY"}),
    ("Knight Therapeutics (USA) Inc", {"GUD.TO"}),
    ("Bausch Health Americas, Inc.", {"BHC"}),  # by the "Bausch Health" prefix
    ("ModernaTX, Inc.", {"MRNA"}),  # an alias
    ("JANSSEN RESEARCH & DEVELOPMENT, LLC", {"JNJ"}),  # an alias, extended
    ("MERCK SHARP DOHME", {"MRK"}),
    ("Alphabet", {"GOOG", "GOOGL"}),  # share classes share the name
])
def test_sponsors_match_the_runs_stocks(sponsor, symbols):
    assert SponsorMatcher(NAMES).symbols_for(sponsor) == symbols


@pytest.mark.parametrize("sponsor", [
    "American Regent",  # "American" is an everyday word, and not AIG
    "United Orthopedic Corp",  # not United Therapeutics
    "Genentech, Inc.",  # Roche's: not in either universe
    "BOEHRINGER INGELHEIM",  # private
    "ACADIA",  # ACADIA Pharmaceuticals or Acadia Healthcare: ambiguous
    "",
])
def test_unknown_everyday_or_ambiguous_names_match_nothing(sponsor):
    assert SponsorMatcher(NAMES).symbols_for(sponsor) == set()


def test_an_alias_counts_only_when_its_stock_is_in_the_run():
    matcher = SponsorMatcher({"PFE": NAMES["PFE"]})
    assert matcher.symbols_for("ModernaTX, Inc.") == set()
