import pytest

from advisor.benchmark.job import ABLATIONS, bagging_twins
from advisor.model.variants import ModelConfig


def test_every_bagged_row_is_judged_against_the_same_row_without_bagging():
    assert bagging_twins(ABLATIONS) == {"ranker+extras+bagged": "ranker+extras"}


def test_a_bagged_row_without_its_twin_is_refused():
    with pytest.raises(ValueError, match="extras\\+bagged has no row without bagging"):
        bagging_twins({"baseline": ModelConfig(), "extras+bagged": ModelConfig(extras=True, bagged=True)})
