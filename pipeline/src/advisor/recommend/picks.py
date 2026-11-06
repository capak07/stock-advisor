"""Choose each stock's hold horizon and stop, and rank the pick lists (spec §6.1-§6.3).

The qualify, ratio and sector rules mirror `simulate_picks`, so the backtest gate vouches for them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from advisor.model.backtest import (
    CRYPTO_SWING_HORIZONS,
    PER_SECTOR,
    PICKS_PER_STYLE,
    SWING_HORIZONS,
)
from advisor.models import PredictionRow
from advisor.policy import DEFAULT_POLICY, Policy

SWING_ATR = 2.0
POSITION_ATR = 3.0
POSITION_MAX_DROP = 0.15


@dataclass(frozen=True)
class Choice:
    symbol: str
    horizon: int
    style: str
    p_beat: float
    q10: float
    q50: float
    q90: float
    ratio: float
    cost: float
    score_rank: int | None = None  # a rank-chosen pick's place among the horizon's forecasts (1 = best)
    score_of: int | None = None  # how many stocks were ranked for that horizon


def _ratio(row: PredictionRow) -> float | None:
    """Expected return per unit of spread; None when the range has no width."""
    width = row.q90 - row.q10
    return row.q50 / width if width > 0 else None


def _style(horizon: int) -> str:
    # stock horizons are sessions and coin horizons days; the two sets never overlap
    return "swing" if horizon in SWING_HORIZONS | CRYPTO_SWING_HORIZONS else "position"


def top_by_horizon(rows: Sequence[PredictionRow], n: int) -> dict[int, dict[str, tuple[int, int]]]:
    """Per horizon, the top `n` symbols by P(beat) (ties by symbol) → (rank, how many were ranked).

    `rows` are the market's forecasts, so a stock without one never takes a place. Within a horizon
    P is a monotone map of the model's score, so this is the model's own ranking (spec §11).
    """
    by_h: dict[int, list[PredictionRow]] = {}
    for r in rows:
        if r.p_beat == r.p_beat:  # a NaN P isn't ranked
            by_h.setdefault(r.horizon_days, []).append(r)
    out: dict[int, dict[str, tuple[int, int]]] = {}
    for h, its in by_h.items():
        ordered = sorted(its, key=lambda r: (-r.p_beat, r.symbol))
        out[h] = {r.symbol: (i + 1, len(ordered)) for i, r in enumerate(ordered[:n])}
    return out


def rankable(population: Mapping[str, Sequence[PredictionRow]], sane: Mapping[str, bool]) -> list[PredictionRow]:
    """The forecasts a rank policy ranks: only stocks that passed the sanity checks (a confirmed
    jump, a wide ATR or a missing row never takes a top-N place), as the backtest ranks (spec §11)."""
    return [r for s, rows in population.items() if sane.get(s) for r in rows]


def choose(
    rows: Sequence[PredictionRow], cost: float, sane: bool, policy: Policy = DEFAULT_POLICY,
    top: Mapping[int, Mapping[str, tuple[int, int]]] | None = None,
) -> Choice | None:
    """The best horizon that qualifies, or None (also None when the sanity checks failed).

    `rule="ratio"` ranks by expected return per unit of range; `"p"` ranks by P(beat).
    A tie goes to the shorter horizon. `horizons`, when set, is the only set considered.
    With `policy.top_n`, a row qualifies by being in `top` (`top_by_horizon`) for its horizon
    instead of by P >= `p_buy`.
    """
    if not sane:
        return None
    best: tuple[float, int, PredictionRow, float] | None = None
    for r in rows:
        ratio = _ratio(r)
        if policy.top_n is not None:
            placed = (top or {}).get(r.horizon_days, {}).get(r.symbol)
            if ratio is None or placed is None or not r.q50 > cost:
                continue
        elif ratio is None or not (r.p_beat >= policy.p_buy and r.q50 > cost):  # written so NaN fails
            continue
        if policy.horizons is not None and r.horizon_days not in policy.horizons:
            continue
        key = r.p_beat if policy.rule == "p" else ratio
        if best is None or key > best[0] or (key == best[0] and r.horizon_days < best[1]):
            best = (key, r.horizon_days, r, ratio)
    if best is None:
        return None
    _, _, r, ratio = best
    placed = (top or {}).get(r.horizon_days, {}).get(r.symbol) if policy.top_n is not None else None
    return Choice(
        r.symbol, r.horizon_days, _style(r.horizon_days), r.p_beat, r.q10, r.q50, r.q90, ratio, cost,
        *(placed if placed else (None, None)),
    )


def best_horizon(rows: Sequence[PredictionRow]) -> PredictionRow | None:
    """The best ratio among all rows, qualifying or not (shown for a stock that is not a pick)."""
    best: tuple[float, PredictionRow] | None = None
    for r in rows:
        ratio = _ratio(r)
        if ratio is None:
            continue
        if best is None or ratio > best[0] or (ratio == best[0] and r.horizon_days < best[1].horizon_days):
            best = (ratio, r)
    return best[1] if best else None


def p_rule(policy: Policy) -> Policy:
    """The P-floor version of a policy, for a verdict or action given no market ranking."""
    return policy if policy.top_n is None else replace(policy, top_n=None)


def market_top(
    rows: Mapping[str, Sequence[PredictionRow]], sane: Mapping[str, bool], policy: Policy
) -> dict[int, dict[str, tuple[int, int]]] | None:
    """The market's top-N ranking under a rank policy, the one its picks use; None for a P policy."""
    if policy.top_n is None:
        return None
    return top_by_horizon(rankable({s: r for s, r in rows.items() if r}, sane), policy.top_n)


def choose_for_stock(
    rows: Sequence[PredictionRow], cost: float, sane: bool, policy: Policy,
    top: Mapping[int, Mapping[str, tuple[int, int]]] | None,
) -> Choice | None:
    """One stock's choice for its verdict or holding action: under a rank policy the picks' own
    rule, so a rank pick is a Buy on its page too (owner's decision, 2026-11-06); the P floor when
    no market ranking is given."""
    if policy.top_n is not None and top is not None:
        return choose(rows, cost, sane, policy, top)
    return choose(rows, cost, sane, p_rule(policy))


def because(choice: Choice, benchmark: str) -> str:
    """Why a choice qualified: its place in the ranking, or its P."""
    if choice.score_rank is not None:
        return f"ranked #{choice.score_rank} of {choice.score_of} by the model over {choice.horizon} trading days"
    return f"P(beat {benchmark}) {choice.p_beat:.2f} over {choice.horizon} trading days"


def stop_price(style: str, entry: float, atr_pct: float, policy: Policy = DEFAULT_POLICY) -> float:
    """Swing: `swing_atr` below entry. Position: `position_atr` below, but never more than 15% below."""
    if style == "swing":
        return entry * (1 - policy.swing_atr * atr_pct)
    return max(entry * (1 - policy.position_atr * atr_pct), entry * (1 - POSITION_MAX_DROP))


def rank_picks(choices: Sequence[Choice], sectors: Mapping[str, str | None]) -> list[tuple[Choice, int]]:
    """Per style, best ratio first (ties by symbol), at most 3 per sector and 10 per list.

    A stock with no sector counts alone. Each choice comes back with its rank within its style.
    """
    out: list[tuple[Choice, int]] = []
    for style in ("swing", "position"):
        in_style = sorted((c for c in choices if c.style == style), key=lambda c: (-c.ratio, c.symbol))
        per_sector: dict[str, int] = {}
        kept = 0
        for c in in_style:
            if kept >= PICKS_PER_STYLE:
                break
            sector = sectors.get(c.symbol)
            # only a missing value (None or NaN) is unlabelled; "" is a sector like any other
            group = f"unlabelled:{c.symbol}" if sector is None or sector != sector else sector
            if per_sector.get(group, 0) >= PER_SECTOR:
                continue
            per_sector[group] = per_sector.get(group, 0) + 1
            kept += 1
            out.append((c, kept))
    return out
