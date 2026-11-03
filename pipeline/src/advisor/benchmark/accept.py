"""Whether a model addition earns its place, judged on untouched outer folds only.

A candidate must rank stocks better overall and in most periods, keep its ranges about as tight,
and keep its probabilities honest. Every rule fails closed: a number that couldn't be measured
never passes. Among the ablation rows that pass, the best ranking wins, and it must also beat the
configuration already accepted, so the accepted choice only changes on evidence.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from advisor.benchmark.metrics import summary
from advisor.model.backtest import MAX_CALIBRATION_PTS

PINBALL_TOLERANCE = 0.005  # a candidate's pooled pinball loss may be at most 0.5% worse
MIN_FOLDS_IMPROVED = 3  # of the 4 outer folds: one lucky period can't carry an addition
# The accepted configuration keeps its place up to this calibration gap; a newcomer needs
# MAX_CALIBRATION_PTS. Without the band, one more day of data moving a gap from 4.9 to 5.1
# flips the accepted choice back and forth (owner's decision of 2026-11-03).
INCUMBENT_CALIBRATION_PTS = MAX_CALIBRATION_PTS + 0.5


@dataclass(frozen=True)
class Scores:
    """One variant's outer-fold model scores."""

    rank_ic: Mapping[str, float]  # per outer fold ("0".."3") and "pooled"; mean over horizons
    pinball: float  # pooled, mean over horizons and the three quantiles
    calibration: Mapping[int, float]  # pooled, per horizon, in points

    @classmethod
    def of(cls, metrics: Mapping[str, Mapping[int, Mapping[str, float]]], horizons: Sequence[int]) -> "Scores":
        """From `model_metrics`: the horizons' mean per fold, and the pooled calibration per horizon."""
        means = summary(dict(metrics), horizons)
        pooled = metrics["pooled"]
        calibration = {h: pooled[h]["calibration_pts"] for h in horizons if h in pooled}
        return cls({k: m["rank_ic"] for k, m in means.items()}, means["pooled"]["pinball"], calibration)


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reasons: tuple[str, ...]


def _nan(x: float | None) -> bool:
    return x is None or x != x


def _usable(scores: Scores) -> list[int]:
    return sorted(h for h, pts in scores.calibration.items() if not _nan(pts) and pts <= MAX_CALIBRATION_PTS)


def _calibration_failures(candidate: Scores, reference: Scores, limit: float) -> list[str]:
    judged = _usable(reference)
    if not judged:  # nothing to hold the candidate to: it must bring honest probabilities itself
        return [] if _usable(candidate) else [f"no horizon has probabilities within {MAX_CALIBRATION_PTS:g} points"]
    failures = []
    for h in judged:
        pts = candidate.calibration.get(h)
        if _nan(pts):
            failures.append(f"horizon {h}: probabilities couldn't be measured")
        elif not pts <= limit:
            failures.append(f"horizon {h}: probabilities off by {pts:.1f} points (limit {limit:g})")
    return failures


def accept_model(candidate: Scores, reference: Scores, calibration_limit: float = MAX_CALIBRATION_PTS) -> Decision:
    """Every rule is checked and every failure listed, in plain words.

    `calibration_limit` is the gap the candidate may have at each horizon the reference could use.
    """
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

    failures += _calibration_failures(candidate, reference, calibration_limit)

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
    baseline: Scores,
    candidates: Mapping[str, Scores],
    incumbent: tuple[str, Scores] | None,
    twins: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, Decision]]:
    """The model to use, and each candidate's decision against the baseline.

    `incumbent` is the accepted non-baseline configuration, scored in this same benchmark. It is
    held to INCUMBENT_CALIBRATION_PTS rather than MAX_CALIBRATION_PTS; every other rule is the same.
    `twins` maps a candidate to the row it must also beat: a bagged row to the same row without
    bagging, so seed averaging's triple cost is paid only for a measured gain (spec §9). A twin
    that wasn't scored fails the candidate closed.
    """
    decisions = {name: accept_model(scores, baseline) for name, scores in candidates.items()}
    for name, twin in (twins or {}).items():
        if name not in decisions or not decisions[name].accepted:
            continue
        if twin not in candidates:
            decisions[name] = Decision(False, (f"{twin} wasn't scored",))
            continue
        against = accept_model(candidates[name], candidates[twin])
        if not against.accepted:
            decisions[name] = Decision(False, (f"not better than {twin}", *against.reasons))
    passing = [name for name in candidates if decisions[name].accepted]
    # max keeps the first of equals: a tie goes to the earlier row
    best = max(passing, key=lambda name: candidates[name].rank_ic["pooled"]) if passing else None
    if incumbent is not None:
        name, scores = incumbent
        kept = accept_model(scores, baseline, INCUMBENT_CALIBRATION_PTS)
        if name in decisions and not decisions[name].accepted:
            decisions[name] = kept if not kept.accepted else Decision(True, (
                f"kept: the accepted configuration may be off by up to {INCUMBENT_CALIBRATION_PTS:g} points "
                f"(a newcomer needs {MAX_CALIBRATION_PTS:g})",
                *kept.reasons,
            ))
        if kept.accepted:
            if best is None or best == name or not accept_model(candidates[best], scores).accepted:
                return name, decisions
    return best or "baseline", decisions


def accept_policy(candidate: Mapping, default: Mapping) -> Decision:
    """A tuned policy goes live only if it meets every hard limit and beats today's rules' net
    Sharpe on the outer folds. Today's rules with no trades held cash: a Sharpe of 0."""
    if not candidate["feasible"]:
        return Decision(False, tuple(candidate["failures"]))
    c = candidate["pooled"]["sharpe"]
    d = default["pooled"]["sharpe"] if default["pooled"]["trades"] else 0.0
    if _nan(c):
        return Decision(False, ("net Sharpe couldn't be measured",))
    if _nan(d):
        return Decision(False, ("today's rules' net Sharpe couldn't be measured",))
    if not c > d:
        return Decision(False, (f"net Sharpe {c:.2f} is not above {d:.2f} for today's rules",))
    return Decision(True, (f"net Sharpe {c:.2f} vs {d:.2f} for today's rules, {candidate['pooled']['trades']} trades",))
