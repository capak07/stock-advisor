import pytest

from advisor.benchmark.job import ABLATIONS, bagging_twins
from advisor.model.variants import ModelConfig


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
