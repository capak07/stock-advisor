"""Choose each stock's hold horizon and stop, and rank the pick lists (spec §6.1-§6.3).

The qualify, ratio and sector rules mirror `simulate_picks`, so the backtest gate vouches for them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from advisor.model.backtest import P_MIN, PER_SECTOR, PICKS_PER_STYLE, SWING_HORIZONS
from advisor.models import PredictionRow

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
    return "swing" if horizon in SWING_HORIZONS else "position"


def choose(rows: Sequence[PredictionRow], cost: float, sane: bool) -> Choice | None:
    """The best-ratio horizon that qualifies, or None (also None when the sanity checks failed)."""
    if not sane:
        return None
    best: tuple[float, PredictionRow] | None = None
    for r in rows:
        ratio = _ratio(r)
        if ratio is None or not (r.p_beat >= P_MIN and r.q50 > cost):  # written so NaN fails
            continue
        # a tie goes to the shorter horizon, as in the backtest
        if best is None or ratio > best[0] or (ratio == best[0] and r.horizon_days < best[1].horizon_days):
            best = (ratio, r)
    if best is None:
        return None
    ratio, r = best
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


def stop_price(style: str, entry: float, atr_pct: float) -> float:
    """Swing: 2 ATR below entry. Position: 3 ATR below, but never more than 15% below."""
    if style == "swing":
        return entry * (1 - SWING_ATR * atr_pct)
    return max(entry * (1 - POSITION_ATR * atr_pct), entry * (1 - POSITION_MAX_DROP))


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
