import pytest

from advisor.benchmark.job import ABLATIONS, POLICY_ROW, bagging_twins, rows_for
from advisor.model.crypto import CRYPTO
from advisor.model.variants import ModelConfig
from advisor.models import Market


def test_every_bagged_row_is_judged_against_the_same_row_without_bagging():
    assert bagging_twins(ABLATIONS) == {"ranker+extras+bagged": "ranker+extras"}


def test_a_bagged_row_without_its_twin_is_refused():
    with pytest.raises(ValueError, match="extras\\+bagged has no row without bagging"):
        bagging_twins({"baseline": ModelConfig(), "extras+bagged": ModelConfig(extras=True, bagged=True)})


def test_every_row_is_named_as_its_config_names_itself():
    # an accepted config finds its row by name, so a row named otherwise could never be the incumbent
    assert all(config.name == name for name, config in ABLATIONS.items() if config is not None)


def test_the_ranker_is_also_tried_with_garch():
    assert ABLATIONS["garch+ranker"] == ModelConfig(ranker=True, garch=True)


def test_the_earnings_row_sits_before_the_policy_row_and_runs_for_us_only():
    names = list(ABLATIONS)
    assert ABLATIONS["ranker+earnings"] == ModelConfig(ranker=True, earnings=True)
    assert names.index("ranker+earnings") == names.index(POLICY_ROW) - 1
    assert list(rows_for(Market.US)) == names
    for market in (Market.TSX, CRYPTO):
        assert list(rows_for(market)) == [n for n in names if n != "ranker+earnings"]
