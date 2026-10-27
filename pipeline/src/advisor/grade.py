"""Grading picks (spec §6.5): the early-exit check, and the grading Task 7 adds."""

from collections.abc import Mapping, Sequence

from advisor.models import PredictionRow
from advisor.recommend.verdicts import AVOID_P
from advisor.store.repo import OpenPick


def exit_early(picks: Sequence[OpenPick], rows: Mapping[str, list[PredictionRow]]) -> list[int]:
    """Ids of the picks whose forecast at their own horizon has fallen to the avoid line.

    A pick the run has no forecast for at its horizon isn't flagged.
    """
    flagged = []
    for pick in picks:
        row = next((r for r in rows.get(pick.symbol, []) if r.horizon_days == pick.horizon_days), None)
        if row is not None and row.p_beat <= AVOID_P:
            flagged.append(pick.id)
    return flagged
