"""Choose each stock's hold horizon and stop, and rank the pick lists (spec §6.1-§6.3).

The qualify, ratio and sector rules mirror `simulate_picks`, so the backtest gate vouches for them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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


def _ratio(row: PredictionRow) -> float | None:
    """Expected return per unit of spread; None when the range has no width."""
    width = row.q90 - row.q10
    return row.q50 / width if width > 0 else None


def _style(horizon: int) -> str:
    # stock horizons are sessions and coin horizons days; the two sets never overlap
    return "swing" if horizon in SWING_HORIZONS | CRYPTO_SWING_HORIZONS else "position"


def choose(
    rows: Sequence[PredictionRow], cost: float, sane: bool, policy: Policy = DEFAULT_POLICY
) -> Choice | None:
    """The best horizon that qualifies, or None (also None when the sanity checks failed).

    `rule="ratio"` ranks by expected return per unit of range; `"p"` ranks by P(beat).
    A tie goes to the shorter horizon. `horizons`, when set, is the only set considered.
    """
    if not sane:
        return None
    best: tuple[float, int, PredictionRow, float] | None = None
    for r in rows:
        ratio = _ratio(r)
        if ratio is None or not (r.p_beat >= policy.p_buy and r.q50 > cost):  # written so NaN fails
            continue
        if policy.horizons is not None and r.horizon_days not in policy.horizons:
            continue
        key = r.p_beat if policy.rule == "p" else ratio
        if best is None or key > best[0] or (key == best[0] and r.horizon_days < best[1]):
            best = (key, r.horizon_days, r, ratio)
    if best is None:
        return None
    _, _, r, ratio = best
    return Choice(r.symbol, r.horizon_days, _style(r.horizon_days), r.p_beat, r.q10, r.q50, r.q90, ratio, cost)


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
