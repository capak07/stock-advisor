"""Whether a model addition earns its place, judged on untouched outer folds only.

A candidate must rank stocks better overall and in most periods, keep its ranges about as tight,
and keep its probabilities honest. Every rule fails closed: a number that couldn't be measured
never passes. Among the ablation rows that pass, the best ranking wins, and it must also beat the
configuration already accepted, so the accepted choice only changes on evidence.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from advisor.model.backtest import MAX_CALIBRATION_PTS

PINBALL_TOLERANCE = 0.005  # a candidate's pooled pinball loss may be at most 0.5% worse
MIN_FOLDS_IMPROVED = 3  # of the 4 outer folds: one lucky period can't carry an addition


@dataclass(frozen=True)
class Scores:
    """One variant's outer-fold model scores."""

    rank_ic: Mapping[str, float]  # per outer fold ("0".."3") and "pooled"; mean over horizons
    pinball: float  # pooled, mean over horizons and the three quantiles
    calibration: Mapping[int, float]  # pooled, per horizon, in points


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reasons: tuple[str, ...]


def _nan(x: float | None) -> bool:
    return x is None or x != x


def _usable(scores: Scores) -> list[int]:
    return sorted(h for h, pts in scores.calibration.items() if not _nan(pts) and pts <= MAX_CALIBRATION_PTS)


def _calibration_failures(candidate: Scores, reference: Scores) -> list[str]:
    judged = _usable(reference)
    if not judged:  # nothing to hold the candidate to: it must bring honest probabilities itself
        return [] if _usable(candidate) else [f"no horizon has probabilities within {MAX_CALIBRATION_PTS:g} points"]
    failures = []
    for h in judged:
        pts = candidate.calibration.get(h)
        if _nan(pts):
            failures.append(f"horizon {h}: probabilities couldn't be measured")
        elif not pts <= MAX_CALIBRATION_PTS:
            failures.append(f"horizon {h}: probabilities off by {pts:.1f} points (limit {MAX_CALIBRATION_PTS:g})")
    return failures


def accept_model(candidate: Scores, reference: Scores) -> Decision:
    """Every rule is checked and every failure listed, in plain words."""
    failures = []
    c_ic, r_ic = candidate.rank_ic.get("pooled"), reference.rank_ic.get("pooled")
    if _nan(c_ic) or _nan(r_ic):
        failures.append("rank IC couldn't be measured")
    elif not c_ic > r_ic:
        failures.append(f"rank IC {c_ic:.3f} is not above {r_ic:.3f}")

    if _nan(candidate.pinball) or _nan(reference.pinball):
        failures.append("pinball loss couldn't be measured")
    elif not candidate.pinball <= reference.pinball * (1 + PINBALL_TOLERANCE):
        worse = (candidate.pinball / reference.pinball - 1) * 100
        failures.append(f"pinball loss {worse:.1f}% worse (limit {PINBALL_TOLERANCE * 100:g}%)")

    failures += _calibration_failures(candidate, reference)

    folds = [k for k in reference.rank_ic if k != "pooled"]
    better = sum(
        1 for k in folds
        if not _nan(candidate.rank_ic.get(k)) and not _nan(reference.rank_ic[k])
        and candidate.rank_ic[k] > reference.rank_ic[k]
    )
    if better < MIN_FOLDS_IMPROVED:
        failures.append(f"rank IC better in {better} of {len(folds)} outer folds (needs {MIN_FOLDS_IMPROVED})")

    if failures:
        return Decision(False, tuple(failures))
    return Decision(True, (f"rank IC {c_ic:.3f} vs {r_ic:.3f}, better in {better} of {len(folds)} outer folds",))


def choose_model(
    baseline: Scores, candidates: Mapping[str, Scores], incumbent: tuple[str, Scores] | None
) -> tuple[str, dict[str, Decision]]:
    """The model to use, and each candidate's decision against the baseline.

    `incumbent` is the accepted non-baseline configuration, scored in this same benchmark.
    """
    decisions = {name: accept_model(scores, baseline) for name, scores in candidates.items()}
    passing = [name for name in candidates if decisions[name].accepted]
    # max keeps the first of equals: a tie goes to the earlier row
    best = max(passing, key=lambda name: candidates[name].rank_ic["pooled"]) if passing else None
    if incumbent is not None:
        name, scores = incumbent
        if accept_model(scores, baseline).accepted:
            if best is None or best == name or not accept_model(candidates[best], scores).accepted:
                return name, decisions
    return best or "baseline", decisions
