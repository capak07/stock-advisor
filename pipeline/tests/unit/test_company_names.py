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
