import pytest

from advisor.benchmark import report
from advisor.benchmark.job import (
    ABLATIONS,
    BASE_ROWS,
    GROUP_BASE,
    POLICY_ROW,
    US_ONLY,
    base_row,
    base_rows,
    combined_config,
    rows_for,
)
from advisor.model.crypto import CRYPTO
from advisor.model.groups import DATA_GROUPS
from advisor.model.variants import ModelConfig
from advisor.models import Market


def test_every_group_row_is_judged_against_the_base_row_and_bagging_against_its_twin():
    rows = base_rows(ABLATIONS)
    assert rows["garch+ranker+forest+short"] == "garch+ranker+forest"
    assert rows["ranker+earnings"] == "ranker"
    assert base_rows({"ranker+extras": ModelConfig(ranker=True, extras=True),
                      "ranker+extras+bagged": ModelConfig(ranker=True, extras=True, bagged=True)}) == {
        "ranker+extras+bagged": "ranker+extras"}


def test_a_row_without_its_base_row_is_refused():
    with pytest.raises(ValueError, match="extras\\+bagged has no base row"):
        base_rows({"baseline": ModelConfig(), "extras+bagged": ModelConfig(extras=True, bagged=True)})


def test_the_base_row_turns_off_bagging_and_every_data_group():
    grouped = ModelConfig(ranker=True, garch=True, forest=True, short=True, catalysts=True, bagged=True)
    assert base_row(grouped) == ABLATIONS[GROUP_BASE]
    assert base_row(ModelConfig(ranker=True)) is None
    assert BASE_ROWS == base_rows(ABLATIONS)
    assert set(BASE_ROWS) == {"ranker+earnings", *(f"{GROUP_BASE}+{group}" for group in DATA_GROUPS)}


def test_the_retired_rows_are_gone_and_factors_garch_stays():
    assert not {"factors", "extras", "ranker+extras", "ranker+extras+bagged"} & set(ABLATIONS)
    assert "factors+garch" in ABLATIONS


def test_the_group_rows_run_for_us_only_before_the_policy_row():
    names = list(ABLATIONS)
    groups = [n for n in names if n.startswith("garch+ranker+forest+")]
    assert len(groups) == 8 and names.index(POLICY_ROW) == len(names) - 1
    assert US_ONLY == {"ranker+earnings", *groups}
    for market in (Market.TSX, CRYPTO):
        assert not set(groups) & set(rows_for(market))


def test_the_combined_row_needs_two_groups_that_passed():
    assert combined_config(["short"]) is None
    assert combined_config([]) is None
    assert combined_config(["short", "estimates"]).name == "garch+ranker+forest+short+estimates"


def test_the_report_lists_the_rows_in_the_benchmark_order():
    assert report._ABLATION_ORDER == tuple(ABLATIONS)


def test_every_row_is_named_as_its_config_names_itself():
    # an accepted config finds its row by name, so a row named otherwise could never be the incumbent
    assert all(config.name == name for name, config in ABLATIONS.items() if config is not None)


def test_the_ranker_is_also_tried_with_garch():
    assert ABLATIONS["garch+ranker"] == ModelConfig(ranker=True, garch=True)


def test_the_forest_row_follows_the_ranker_with_garch_in_every_market():
    names = list(ABLATIONS)
    assert ABLATIONS["garch+ranker+forest"] == ModelConfig(ranker=True, garch=True, forest=True)
    assert names.index("garch+ranker+forest") == names.index("garch+ranker") + 1
    for market in (Market.US, Market.TSX, CRYPTO):
        assert "garch+ranker+forest" in rows_for(market)


def test_the_earnings_row_sits_before_the_group_rows_and_runs_for_us_only():
    names = list(ABLATIONS)
    assert ABLATIONS["ranker+earnings"] == ModelConfig(ranker=True, earnings=True)
    assert names == [
        "baseline", "ranker", "garch", "factors+garch", "garch+ranker", "garch+ranker+forest", "ranker+earnings",
        *(f"garch+ranker+forest+{group}" for group in DATA_GROUPS), POLICY_ROW,
    ]
    assert list(rows_for(Market.US)) == names
    for market in (Market.TSX, CRYPTO):
        assert list(rows_for(market)) == [n for n in names if n not in US_ONLY]
