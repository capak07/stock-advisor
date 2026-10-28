"""The recommendation policy: buy and sell lines, stop multipliers, and the horizon rule.

`DEFAULT_POLICY` is today's rules. A stored policy that this code can't read falls back to it.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_KEYS = ("p_buy", "p_sell", "swing_atr", "position_atr", "trail_atr", "rule", "horizons")
_RULES = ("ratio", "p")
_MULTIPLIERS = ("swing_atr", "position_atr", "trail_atr")


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, not {type(value).__name__}")
    return float(value)


@dataclass(frozen=True)
class Policy:
    p_buy: float
    p_sell: float
    swing_atr: float
    position_atr: float
    trail_atr: float
    rule: str
    horizons: tuple[int, ...] | None

    def to_json(self) -> dict[str, Any]:
        horizons = None if self.horizons is None else list(self.horizons)
        return {
            "p_buy": self.p_buy,
            "p_sell": self.p_sell,
            "swing_atr": self.swing_atr,
            "position_atr": self.position_atr,
            "trail_atr": self.trail_atr,
            "rule": self.rule,
            "horizons": horizons,
        }

    @classmethod
    def from_json(cls, d: Any) -> "Policy":
        if not isinstance(d, Mapping):
            raise ValueError(f"a policy must be a mapping, not {type(d).__name__}")
        if set(d) != set(_KEYS):
            odd = sorted(set(d) ^ set(_KEYS))
            raise ValueError(f"a policy has unexpected or missing keys: {', '.join(odd)}")
        p_buy, p_sell = _number(d["p_buy"], "p_buy"), _number(d["p_sell"], "p_sell")
        if p_sell >= p_buy:
            raise ValueError(f"p_sell {p_sell} must be below p_buy {p_buy}")
        multipliers = {name: _number(d[name], name) for name in _MULTIPLIERS}
        if any(value <= 0 for value in multipliers.values()):
            raise ValueError("stop multipliers must be positive")
        if d["rule"] not in _RULES:
            raise ValueError(f"rule must be 'ratio' or 'p', not {d['rule']!r}")
        return cls(p_buy, p_sell, multipliers["swing_atr"], multipliers["position_atr"],
                   multipliers["trail_atr"], d["rule"], _horizons(d["horizons"]))


def _horizons(value: Any) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) or not value:
        raise ValueError("horizons must be a list of days, or null")
    days = []
    for day in value:
        if isinstance(day, bool) or not isinstance(day, int):
            raise ValueError("horizons must be a list of days, or null")
        days.append(day)
    return tuple(days)


# Today's rules. These match P_MIN, AVOID_P, SWING_ATR, POSITION_ATR and TRAIL_ATR; importing
# those here would cycle once the live modules import Policy.
DEFAULT_POLICY = Policy(0.58, 0.42, 2.0, 3.0, 2.5, "ratio", None)


def policy_of(metrics: Mapping) -> Policy:
    """The policy stored with a model, or today's rules when it's absent or unreadable."""
    config = metrics.get("config") if isinstance(metrics, Mapping) else None
    if not isinstance(config, Mapping) or config.get("policy") is None:
        return DEFAULT_POLICY
    try:
        return Policy.from_json(config["policy"])
    except ValueError:
        return DEFAULT_POLICY
