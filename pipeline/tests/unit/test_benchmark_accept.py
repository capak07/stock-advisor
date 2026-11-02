import pytest

from advisor.benchmark.accept import Scores, accept_model, choose_model


def scores(ic=0.05, folds=(0.05, 0.05, 0.05, 0.05), pinball=0.010, cal=None):
    return Scores({**{str(k): v for k, v in enumerate(folds)}, "pooled": ic}, pinball, cal or {5: 3.0, 63: 4.0})


BASE = scores(ic=0.04, folds=(0.04,) * 4)


def test_a_better_candidate_passes():
    d = accept_model(scores(), BASE)
    assert d.accepted and d.reasons == ("rank IC 0.050 vs 0.040, better in 4 of 4 outer folds",)


def test_one_lucky_period_cannot_carry_it():
    d = accept_model(scores(ic=0.045, folds=(0.05, 0.05, 0.03, 0.03)), BASE)
    assert not d.accepted and "rank IC better in 2 of 4 outer folds (needs 3)" in d.reasons


def test_equal_rank_ic_is_not_an_improvement():
    d = accept_model(BASE, BASE)
    assert not d.accepted and "rank IC 0.040 is not above 0.040" in d.reasons


def test_pinball_may_worsen_by_half_a_percent_and_no_more():
    assert accept_model(scores(pinball=0.01004), BASE).accepted
    d = accept_model(scores(pinball=0.01006), BASE)
    assert not d.accepted and "pinball loss 0.6% worse (limit 0.5%)" in d.reasons


def test_calibration_is_judged_on_the_horizons_the_reference_could_use():
    d = accept_model(scores(cal={5: 3.0, 63: 5.4}), BASE)
    assert not d.accepted and "horizon 63: probabilities off by 5.4 points (limit 5)" in d.reasons
    unusable_63 = scores(ic=0.04, folds=(0.04,) * 4, cal={5: 3.0, 63: 6.0})
    assert accept_model(scores(cal={5: 3.0, 63: 7.0}), unusable_63).accepted


@pytest.mark.parametrize("candidate", [
    scores(ic=float("nan")),
    scores(pinball=float("nan")),
    scores(cal={5: 3.0}),
    scores(cal={5: 3.0, 63: float("nan")}),
])
def test_anything_unmeasured_fails_closed(candidate):
    assert not accept_model(candidate, BASE).accepted


def test_an_unmeasured_calibration_says_so():
    d = accept_model(scores(cal={5: 3.0}), BASE)
    assert "horizon 63: probabilities couldn't be measured" in d.reasons


def test_every_failed_rule_is_listed():
    d = accept_model(scores(ic=0.03, folds=(0.03,) * 4, pinball=0.02, cal={5: 3.0, 63: 9.0}), BASE)
    assert len(d.reasons) == 4


def test_the_best_passing_row_is_chosen_and_a_combination_must_pass_on_its_own():
    name, decisions = choose_model(BASE, {
        "factors": scores(ic=0.05),
        "garch": scores(ic=0.06, folds=(0.06,) * 4),
        "factors+garch": scores(ic=0.07, folds=(0.07, 0.07, 0.01, 0.01)),
    }, None)
    assert name == "garch" and not decisions["factors+garch"].accepted
    assert set(decisions) == {"factors", "garch", "factors+garch"}
    assert choose_model(BASE, {"factors": scores(ic=0.03, folds=(0.03,) * 4)}, None)[0] == "baseline"


def test_a_tie_goes_to_the_earlier_row():
    assert choose_model(BASE, {"factors": scores(), "garch": scores()}, None)[0] == "factors"


def test_a_challenger_must_also_beat_the_incumbent():
    incumbent = scores(ic=0.055, folds=(0.055,) * 4)
    challenger = scores(ic=0.06, folds=(0.06, 0.06, 0.05, 0.05))  # beats the baseline, not the incumbent
    assert choose_model(BASE, {"factors": incumbent, "garch": challenger}, ("factors", incumbent))[0] == "factors"
    fallen = scores(ic=0.03, folds=(0.03,) * 4)  # the incumbent no longer beats the baseline
    assert choose_model(BASE, {"factors": fallen, "garch": challenger}, ("factors", fallen))[0] == "garch"


def test_a_challenger_that_beats_the_incumbent_replaces_it():
    incumbent = scores(ic=0.05)
    challenger = scores(ic=0.06, folds=(0.06,) * 4)
    assert choose_model(BASE, {"factors": incumbent, "garch": challenger}, ("factors", incumbent))[0] == "garch"


def test_with_no_honest_baseline_horizon_the_candidate_must_bring_one():
    dishonest = scores(ic=0.04, folds=(0.04,) * 4, cal={5: 6.0, 63: 7.0})
    d = accept_model(scores(cal={5: 6.5, 63: 8.0}), dishonest)
    assert not d.accepted and "no horizon has probabilities within 5 points" in d.reasons
    assert accept_model(scores(cal={5: 4.0, 63: 8.0}), dishonest).accepted


def test_scores_are_read_from_the_per_fold_metrics():
    nan = float("nan")
    metrics = {
        "0": {5: {"rank_ic": 0.10, "pinball": 0.02, "calibration_pts": nan}},
        "1": {5: {"rank_ic": 0.02, "pinball": 0.01, "calibration_pts": 4.0},
              63: {"rank_ic": 0.04, "pinball": 0.03, "calibration_pts": 2.0}},
        "pooled": {5: {"rank_ic": 0.05, "pinball": 0.01, "calibration_pts": 3.0},
                   63: {"rank_ic": 0.07, "pinball": 0.03, "calibration_pts": 6.0}},
    }
    s = Scores.of(metrics, (5, 63))
    assert s.rank_ic == {"0": pytest.approx(0.10), "1": pytest.approx(0.03), "pooled": pytest.approx(0.06)}
    assert s.pinball == pytest.approx(0.02)
    assert s.calibration == {5: 3.0, 63: 6.0}


def book(sharpe, trades=40, feasible=True, failures=()):
    return {"pooled": {"sharpe": sharpe, "trades": trades}, "feasible": feasible, "failures": list(failures)}


def test_a_policy_must_beat_todays_rules_or_cash():
    from advisor.benchmark.accept import accept_policy
    d = accept_policy(book(0.8), book(float("nan"), trades=0))  # today's rules never traded: cash
    assert d.accepted and d.reasons == ("net Sharpe 0.80 vs 0.00 for today's rules, 40 trades",)
    assert not accept_policy(book(0.8), book(1.1)).accepted
    assert "net Sharpe 0.80 is not above 1.10 for today's rules" in accept_policy(book(0.8), book(1.1)).reasons
    assert not accept_policy(book(-0.2), book(float("nan"), trades=0)).accepted
    assert not accept_policy(book(float("nan")), book(0.0, trades=0)).accepted
    infeasible = accept_policy(book(2.0, feasible=False, failures=["only 12 trades (needs 30)"]), book(0.0, trades=0))
    assert not infeasible.accepted and infeasible.reasons == ("only 12 trades (needs 30)",)


TWINS = {"ranker+extras+bagged": "ranker+extras"}


def test_a_bagged_row_must_also_beat_the_same_row_without_bagging():
    twin = scores(ic=0.05)
    noise = scores(ic=0.0502, folds=(0.06, 0.06, 0.045, 0.045))  # beats the baseline, not its twin
    name, decisions = choose_model(BASE, {"ranker+extras": twin, "ranker+extras+bagged": noise}, None, TWINS)
    assert name == "ranker+extras"
    d = decisions["ranker+extras+bagged"]
    assert not d.accepted and d.reasons[0] == "not better than ranker+extras"
    assert "rank IC better in 2 of 4 outer folds (needs 3)" in d.reasons


def test_a_bagged_row_that_beats_its_twin_can_win():
    twin, better = scores(ic=0.05), scores(ic=0.06, folds=(0.06,) * 4)
    assert choose_model(BASE, {"ranker+extras": twin, "ranker+extras+bagged": better}, None, TWINS)[0] == (
        "ranker+extras+bagged"
    )


def test_a_bagged_row_whose_twin_was_not_scored_fails_closed():
    name, decisions = choose_model(BASE, {"ranker+extras+bagged": scores(ic=0.06, folds=(0.06,) * 4)}, None, TWINS)
    assert name == "baseline"
    assert decisions["ranker+extras+bagged"].reasons == ("ranker+extras wasn't scored",)
