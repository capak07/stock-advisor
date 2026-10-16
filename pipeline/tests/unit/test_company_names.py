import pytest

from advisor.company_names import CompanyNames, search_name, short_name


@pytest.mark.parametrize(
    ("directory_name", "search", "short"),
    [  # NASDAQ, NYSE (otherlisted.txt) and TMX forms
        ("Apple Inc. - Common Stock", "Apple Inc", "Apple"),
        ("United Airlines Holdings, Inc. - Common Stock", "United Airlines Holdings, Inc", "United Airlines"),
        ("Alphabet Inc. - Class A Common Stock", "Alphabet Inc", "Alphabet"),
        ("Berkshire Hathaway Inc. Class B Common Stock", "Berkshire Hathaway Inc", "Berkshire Hathaway"),
        ("JPMorgan Chase & Co. Common Stock", "JPMorgan Chase & Co", "JPMorgan Chase"),
        (
            "Energy Transfer LP Common Units representing limited partner interests",
            "Energy Transfer LP", "Energy Transfer",
        ),
        (
            "Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares",
            "Taiwan Semiconductor Manufacturing Company Ltd", "Taiwan Semiconductor Manufacturing",
        ),
        ("The Home Depot, Inc. Common Stock", "The Home Depot, Inc", "Home Depot"),
        ("Walt Disney Company (The) Common Stock", "Walt Disney Company", "Walt Disney"),
        ("Kraft Heinz Company (The) - Common Stock", "Kraft Heinz Company", "Kraft Heinz"),
        ("Goldman Sachs Group, Inc. (The) Common Stock", "Goldman Sachs Group, Inc", "Goldman Sachs"),
        # NYSE forms from the live directory (Plan 2f final review)
        ("Berkshire Hathaway Inc. New Common Stock", "Berkshire Hathaway Inc", "Berkshire Hathaway"),
        (
            "American International Group, Inc. New Common Stock",
            "American International Group, Inc", "American International",
        ),
        (
            "Apollo Global Management, Inc. (New) Common Stock",
            "Apollo Global Management, Inc", "Apollo Global Management",
        ),
        ("American Tower Corporation (REIT) Common Stock", "American Tower Corporation", "American Tower"),
        ("Brookfield Corporation Class A Limited Voting Shares", "Brookfield Corporation", "Brookfield"),
        (
            "Brookfield Renewable Partners L.P. Limited Partnership Units",
            "Brookfield Renewable Partners L.P", "Brookfield Renewable Partners",
        ),
        (
            "GFL Environmental Inc. Subordinate voting shares, no par value",
            "GFL Environmental Inc", "GFL Environmental",
        ),
        ("Banco Macro S.A.  ADR (representing Ten Class B Common Shares)", "Banco Macro S.A", "Banco Macro"),
        (
            "Ambow Education Holding Ltd. American Depository Shares"
            " (each representing twenty (20) Class A Ordinary Shares)",
            "Ambow Education Holding Ltd", "Ambow Education",
        ),
        (
            "Bank of N.T. Butterfield & Son Limited (The) Voting Ordinary Shares",
            "Bank of N.T. Butterfield & Son", "Bank of N.T. Butterfield & Son",
        ),
        ("Aegon Ltd. New York Registry Shares", "Aegon Ltd", "Aegon"),
        ("Central Pacific Financial Corp New", "Central Pacific Financial Corp", "Central Pacific Financial"),
        (
            "DAQO New Energy Corp. American Depositary Shares, each representing five ordinary shares",
            "DAQO New Energy Corp", "DAQO New Energy",
        ),
        ("PermRock Royalty Trust Units of Beneficial Interest", "PermRock Royalty Trust", "PermRock Royalty Trust"),
        (
            "51Talk Online Education Group American depositary shares, each representing 60 Class A"
            " ordinary shares",
            "51Talk Online Education Group", "51Talk Online Education",
        ),
        ("Arcos Dorados Holdings Inc. Class A Shares", "Arcos Dorados Holdings Inc", "Arcos Dorados"),
        ("Anheuser-Busch Inbev SA Sponsored ADR (Belgium)", "Anheuser-Busch Inbev SA", "Anheuser-Busch Inbev"),
        ("SAP  SE ADS", "SAP SE", "SAP"),
        ("Koninklijke Philips N.V. NY Registry Shares", "Koninklijke Philips N.V", "Koninklijke Philips"),
        ("Jerash Holdings (US), Inc", "Jerash Holdings, Inc", "Jerash"),
        ("Duke Energy Corporation (Holding Company)", "Duke Energy Corporation", "Duke Energy"),
        ("Gildan Activewear, Inc. Class A Sub. Vot. Common Stock", "Gildan Activewear, Inc", "Gildan Activewear"),
        ("Lennar Corporation Class B", "Lennar Corporation", "Lennar"),
        ("Janus Living, Inc. Class A-1 Common Stock", "Janus Living, Inc", "Janus Living"),
        ("Hess Midstream LP Class A Representing Limited Partner Interests", "Hess Midstream LP", "Hess Midstream"),
        (
            "WaterBridge Infrastructure LLC Class A Shares Representing Limited Liability Company Interests",
            "WaterBridge Infrastructure LLC", "WaterBridge Infrastructure",
        ),
        ("World Class Holdings Inc.", "World Class Holdings Inc", "World Class"),
        (
            "NIO Inc. American depositary shares, each  representing one Class A ordinary share",
            "NIO Inc", "NIO",
        ),
        # words that only look like an instrument stay
        (
            "Morgan Stanley China A Share Fund Inc. Common Stock",
            "Morgan Stanley China A Share Fund Inc", "Morgan Stanley China A Share Fund",
        ),
        (
            "The Bank of New York Mellon Corporation Common Stock",
            "The Bank of New York Mellon Corporation", "Bank of New York Mellon",
        ),
        (
            "GraniteShares Gold Trust Shares of Beneficial Interest",
            "GraniteShares Gold Trust", "GraniteShares Gold Trust",
        ),
        ("Royal Bank of Canada", "Royal Bank of Canada", "Royal Bank of Canada"),
        ("Shopify Inc.", "Shopify Inc", "Shopify"),
        ("Canadian National Railway Company", "Canadian National Railway Company", "Canadian National Railway"),
        ("Commonwealth Edison Company", "Commonwealth Edison Company", "Commonwealth Edison"),
    ],
)
def test_names_for_searching_and_for_headlines(directory_name, search, short):
    assert (search_name(directory_name), short_name(directory_name)) == (search, short)


def test_names_are_filled_by_the_run():
    names = CompanyNames()
    assert names.get("AAPL") is None
    names.update({"AAPL": "Apple Inc. - Common Stock"})
    assert names.get("AAPL") == "Apple Inc. - Common Stock"
    assert names.items() == [("AAPL", "Apple Inc. - Common Stock")]
