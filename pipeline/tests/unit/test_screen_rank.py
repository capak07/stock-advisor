import pytest

from advisor.screen_rank import LOW_SHARE, MIN_SCORED, screen_ranks


def test_the_bottom_tenth_of_the_scores_is_flagged_low():
    scores = {f"S{i:03d}": float(i) for i in range(200)}
    ranks = {r.symbol: r for r in screen_ranks(scores)}
    assert len(ranks) == 200
    low = sorted(s for s, r in ranks.items() if r.low)
    assert low == [f"S{i:03d}" for i in range(20)]  # 10% of 200
    assert ranks["S000"].pct == pytest.approx(1 / 200)
    assert ranks["S199"].pct == pytest.approx(1.0)
    assert all(r.pct <= LOW_SHARE for r in ranks.values() if r.low)


def test_too_few_scores_flag_nothing():
    assert screen_ranks({f"S{i}": float(i) for i in range(MIN_SCORED - 1)}) == []


def test_tied_scores_share_one_rank():
    scores = {f"S{i:03d}": 0.0 for i in range(150)} | {"TOP": 1.0}
    ranks = {r.symbol: r for r in screen_ranks(scores)}
    assert len({r.pct for s, r in ranks.items() if s != "TOP"}) == 1
    assert not any(r.low for r in ranks.values())  # a tie at the bottom is not a bottom tenth
