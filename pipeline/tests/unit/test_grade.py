from datetime import date

from advisor.grade import exit_early
from advisor.models import PredictionRow
from advisor.store.repo import OpenPick


def _pick(id: int, horizon_days: int = 63, symbol: str = "AAA") -> OpenPick:
    return OpenPick(
        id=id, symbol=symbol, market="TSX", horizon_days=horizon_days, exit_by=date(2027, 1, 13),
        entry_ref_price=10.0, stop=9.0, feature_day=date(2026, 10, 13), bench_ref_price=20.0, run_kind="pre_open",
    )


def _row(symbol: str, h: int, p: float) -> PredictionRow:
    return PredictionRow(symbol, h, -0.05, 0.01, 0.07, p, "XIU.TO", "v1")


def test_exit_early_flags_a_pick_whose_p_fell_to_0_42():
    picks = [_pick(1, symbol="AAA"), _pick(2, symbol="BBB"), _pick(3, symbol="CCC"), _pick(4, 21, "DDD")]
    rows = {
        "AAA": [_row("AAA", 63, 0.42)],
        "BBB": [_row("BBB", 63, 0.43)],
        # CCC has no row this run; DDD has rows, but not at its own horizon (21)
        "DDD": [_row("DDD", 63, 0.10)],
    }
    assert exit_early(picks, rows) == [1]


def test_exit_early_reads_the_row_at_the_picks_own_horizon():
    rows = {"AAA": [_row("AAA", 21, 0.10), _row("AAA", 63, 0.60)]}
    assert exit_early([_pick(1, 63)], rows) == []
    assert exit_early([_pick(2, 21)], rows) == [2]
