from datetime import UTC, datetime

from advisor.model.weekly import calibration_of, should_promote, usable_horizons, version_for
from advisor.models import Market, StoredModel

NAN = float("nan")
NOW = datetime(2026, 10, 24, 10, tzinfo=UTC)


def stored(ic: float) -> StoredModel:
    return StoredModel("stock_us-202610171000", "stock_us", datetime(2026, 10, 17, 10, tzinfo=UTC),
                       {"mean_rank_ic": ic}, 3.0, True)


def test_versions_name_the_market_and_the_minute():
    assert version_for(Market.TSX, datetime(2026, 10, 24, 10, 5, tzinfo=UTC)) == "stock_tsx-202610241005"


def test_a_new_model_needs_honest_probabilities_and_no_worse_ranking():
    assert should_promote({"mean_rank_ic": 0.05}, 3.0, None, NOW) == (True, "first model")
    assert should_promote({"mean_rank_ic": 0.05}, 5.4, None, NOW) == (False, "probabilities off by 5.4 points (limit 5)")
    assert should_promote({"mean_rank_ic": 0.047}, 3.0, stored(0.05), NOW) == (True, "rank IC 0.047 vs the active 0.050")
    assert should_promote({"mean_rank_ic": 0.040}, 3.0, stored(0.05), NOW) == (False, "rank IC 0.040 vs the active 0.050")


def test_a_model_whose_checks_could_not_be_measured_is_never_promoted():
    no_cal = (False, "probabilities couldn't be checked (no calibrated predictions)")
    no_ic = (False, "rank IC couldn't be measured")
    assert should_promote({"mean_rank_ic": 0.05}, NAN, None, NOW) == no_cal
    assert should_promote({"mean_rank_ic": 0.05}, NAN, stored(0.05), NOW) == no_cal
    assert should_promote({"mean_rank_ic": NAN}, 3.0, None, NOW) == no_ic
    assert should_promote({"mean_rank_ic": NAN}, 3.0, stored(0.05), NOW) == no_ic
    assert should_promote({"mean_rank_ic": 0.05}, 3.0, stored(NAN), NOW) == no_ic


def test_calibration_is_the_worst_horizon_and_nan_if_any_horizon_is_unmeasured():
    def of(a, b):
        return calibration_of({5: {"calibration_pts": a}, 63: {"calibration_pts": b}}, (5, 63))

    assert of(3.0, 4.2) == 4.2
    assert of(4.2, 3.0) == 4.2
    assert of(NAN, 3.0) != of(NAN, 3.0)  # NaN, whichever order the horizons come in
    assert of(3.0, NAN) != of(3.0, NAN)
    assert calibration_of({}, (5, 63)) != calibration_of({}, (5, 63))
    assert calibration_of({5: {"calibration_pts": 3.0}}, (5, 63)) != calibration_of({5: {"calibration_pts": 3.0}}, (5, 63))


def test_a_horizon_is_usable_only_when_measured_and_within_five_points():
    m = {5: {"calibration_pts": 2.0}, 21: {"calibration_pts": 5.0}, 63: {"calibration_pts": 6.1},
         126: {"calibration_pts": float("nan")}}
    assert usable_horizons(m, (5, 10, 21, 63, 126)) == (5, 21)  # 10 unmeasured, 63 too far off, 126 NaN
    assert usable_horizons({}, (5,)) == ()


def test_a_model_four_weeks_old_is_replaced_by_any_honest_one():
    old = stored(0.05)  # trained 2026-10-17
    later = datetime(2026, 11, 14, 10, tzinfo=UTC)  # 28 days on
    assert should_promote({"mean_rank_ic": 0.01}, 3.0, old, later) == (True, "the active model is 28 days old (limit 28)")
    assert should_promote({"mean_rank_ic": 0.01}, 5.4, old, later)[0] is False  # still needs honest probabilities
    assert should_promote({"mean_rank_ic": float("nan")}, 3.0, old, later)[0] is False
