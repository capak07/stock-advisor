"""Holdings at average cost, built from the buys and sells (spec §7.1); mirrors web/lib/portfolio/ledger.ts."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from advisor.models import AssetType

# Below this, a quantity is a rounding leftover and the position is closed.
QTY_EPSILON = 1e-9


@dataclass(frozen=True)
class Trade:
    side: str  # "buy" or "sell"
    account: str
    symbol: str
    asset_type: AssetType
    qty: float
    price: float
    currency: str
    fx_rate_cad: float | None
    day: date
    pick_id: int | None  # None for sells


@dataclass(frozen=True)
class Position:
    account: str
    symbol: str
    asset_type: AssetType
    qty: float
    cost_cad: float
    opened_on: date
    pick_id: int | None  # the latest pick among the buys since the position opened


@dataclass(frozen=True)
class Loss:
    """A sell that realized a loss."""

    account: str
    symbol: str
    asset_type: AssetType
    day: date


@dataclass(frozen=True)
class Ledger:
    positions: list[Position]
    losses: list[Loss]
    problems: list[str]  # trades that couldn't be applied as entered, in plain words


def rate_on(fx: Mapping[date, float], day: date) -> float | None:
    """The USD/CAD rate of the latest day on or before `day`, if any is known."""
    known = [d for d in fx if d <= day]
    return fx[max(known)] if known else None


def trade_cad(trade: Trade, fx: Mapping[date, float]) -> float | None:
    """A trade's amount in CAD. A USD trade uses its own rate, else the rate of its day; None if unknown."""
    amount = trade.qty * trade.price
    if trade.currency == "CAD":
        return amount
    rate = trade.fx_rate_cad if trade.fx_rate_cad is not None else rate_on(fx, trade.day)
    return None if rate is None else amount * rate


def in_order(trades: Sequence[Trade]) -> list[Trade]:
    """Trades in the order they count: by day, and a day's buys before its sells."""
    return sorted(trades, key=lambda t: (t.day, t.side != "buy"))


def build_ledger(trades: Sequence[Trade], fx: Mapping[date, float]) -> Ledger:
    """Average cost per account and asset. A sell reduces the quantity at average cost; a sell of
    more than is held is applied to what is held."""
    open_: dict[tuple[str, AssetType, str], Position] = {}
    losses: list[Loss] = []
    problems: list[str] = []

    for trade in in_order(trades):
        key = (trade.account, trade.asset_type, trade.symbol)
        cad = trade_cad(trade, fx)
        if cad is None:
            problems.append(
                f"{trade.symbol} on {trade.day}: no USD/CAD rate for that day, so it's left out."
            )
            continue
        held = open_.get(key)
        if trade.side == "buy":
            if held is None:
                open_[key] = Position(
                    trade.account, trade.symbol, trade.asset_type, trade.qty, cad, trade.day,
                    trade.pick_id,
                )
            else:
                open_[key] = replace(
                    held,
                    qty=held.qty + trade.qty,
                    cost_cad=held.cost_cad + cad,
                    pick_id=trade.pick_id if trade.pick_id is not None else held.pick_id,
                )
            continue
        if held is None:
            problems.append(
                f"{trade.symbol} on {trade.day}: a sell with nothing held, so it's left out."
            )
            continue
        qty, proceeds = trade.qty, cad
        if qty > held.qty + QTY_EPSILON:
            problems.append(
                f"{trade.symbol} on {trade.day}: sold {trade.qty:g} but held {held.qty:g};"
                f" counted as {held.qty:g}."
            )
            proceeds = cad * held.qty / qty
            qty = held.qty
        cost = held.cost_cad * qty / held.qty
        if proceeds < cost:
            losses.append(Loss(trade.account, trade.symbol, trade.asset_type, trade.day))
        left = held.qty - qty
        if left <= QTY_EPSILON:
            del open_[key]
        else:
            open_[key] = replace(held, qty=left, cost_cad=held.cost_cad - cost)

    return Ledger(list(open_.values()), losses, problems)
