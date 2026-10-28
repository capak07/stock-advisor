import pytest

from advisor.policy import DEFAULT_POLICY, Policy, policy_of

STORED = {
    "p_buy": 0.58,
    "p_sell": 0.42,
    "swing_atr": 2.0,
    "position_atr": 3.0,
    "trail_atr": 2.5,
    "rule": "ratio",
    "horizons": None,
}


def test_the_default_policy_is_todays_rules():
    from advisor.model.backtest import P_MIN
    from advisor.portfolio.stops import TRAIL_ATR
    from advisor.recommend.picks import POSITION_ATR, SWING_ATR
    from advisor.recommend.verdicts import AVOID_P

    assert DEFAULT_POLICY.to_json() == STORED
    assert (DEFAULT_POLICY.p_buy, DEFAULT_POLICY.p_sell) == (P_MIN, AVOID_P)
    assert (DEFAULT_POLICY.swing_atr, DEFAULT_POLICY.position_atr, DEFAULT_POLICY.trail_atr) == (
        SWING_ATR, POSITION_ATR, TRAIL_ATR,
    )


def test_a_policy_round_trips_including_a_horizon_set():
    policy = Policy(0.60, 0.40, 2.0, 3.0, 2.5, "p", (21, 63, 126))
    assert Policy.from_json(policy.to_json()) == policy
    assert policy.to_json()["horizons"] == [21, 63, 126]


@pytest.mark.parametrize("bad", [
    [],
    {k: v for k, v in STORED.items() if k != "p_buy"},
    STORED | {"extra": 1},
    STORED | {"p_buy": "high"},
    STORED | {"swing_atr": "wide"},
    STORED | {"rule": "score"},
    STORED | {"p_sell": 0.58},
    STORED | {"p_sell": 0.70},
    STORED | {"swing_atr": 0},
    STORED | {"position_atr": -1},
    STORED | {"trail_atr": 0.0},
])
def test_an_invalid_policy_is_refused(bad):
    with pytest.raises(ValueError):
        Policy.from_json(bad)


def test_a_missing_or_invalid_stored_policy_is_todays_rules():
    assert policy_of({}) == DEFAULT_POLICY
    assert policy_of({"config": {"policy": None}}) == DEFAULT_POLICY
    assert policy_of({"config": {"policy": {"bad": 1}}}) == DEFAULT_POLICY


def test_policy_of_returns_a_valid_stored_policy():
    stored = Policy(0.60, 0.40, 1.5, 2.5, 3.0, "p", (5, 10, 20)).to_json()
    assert policy_of({"config": {"policy": stored}}) == Policy.from_json(stored)
