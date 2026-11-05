"""A model configuration (a variant), and the one seam every variant trains through.

The benchmark compares variants on identical folds; weekly training runs the market's accepted
one. `garch` (Plan 6d) trains each horizon on its GARCH forecast volatility (spec §4); the data
must be loaded with `with_garch=True`. A tuned policy is a `Policy` value. `ranker` (Plan 6f) swaps the beat classifier for a ranking booster (spec §8).
`extras` adds the market's extra features and `bagged` averages three seeds per booster (spec §9).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from advisor.model.dataset import MarketData
from advisor.model.train import FinalModel, Fold, TrainConfig, WalkForward, fit_final, walk_forward
from advisor.policy import Policy

CONFIG_VERSION = 3
# version 1 (before Plan 6f) had no `ranker`, version 2 (before Plan 6g) no `extras` or `bagged`;
# both still load, with those parts off
_KEYS = {
    1: {"version", "factors", "garch", "policy"},
    2: {"version", "factors", "garch", "ranker", "policy"},
    3: {"version", "factors", "garch", "ranker", "extras", "bagged", "policy"},
}


@dataclass(frozen=True)
class ModelConfig:
    factors: bool = False
    garch: bool = False
    policy: Policy | None = None  # tuned rules; None = today's constants
    ranker: bool = False
    extras: bool = False
    bagged: bool = False

    @property
    def name(self) -> str:
        parts = (("factors", self.factors), ("garch", self.garch), ("ranker", self.ranker),
                 ("extras", self.extras), ("bagged", self.bagged))
        model = "+".join(part for part, on in parts if on)
        return (model or "baseline") + ("+policy" if self.policy is not None else "")

    def to_json(self) -> dict[str, Any]:
        policy = None if self.policy is None else self.policy.to_json()
        return {
            "version": CONFIG_VERSION, "factors": self.factors, "garch": self.garch, "ranker": self.ranker,
            "extras": self.extras, "bagged": self.bagged, "policy": policy,
        }

    @classmethod
    def from_json(cls, d: Any) -> "ModelConfig":
        """A stored configuration, refused (ValueError) unless this code can run it as written."""
        if not isinstance(d, Mapping):
            raise ValueError(f"a stored config must be a mapping, not {type(d).__name__}")
        keys = _KEYS.get(d.get("version")) if isinstance(d.get("version"), int) else None
        if keys is None:
            raise ValueError(f"unknown config version {d.get('version')!r}")
        if set(d) != keys:
            odd = sorted(set(d) ^ keys)
            raise ValueError(f"a stored config has unexpected or missing keys: {', '.join(odd)}")
        raw = d["policy"]
        policy = None if raw is None else Policy.from_json(raw)
        config = cls(bool(d["factors"]), bool(d["garch"]), policy, bool(d.get("ranker", False)),
                     bool(d.get("extras", False)), bool(d.get("bagged", False)))
        if (plan := unbuilt(config)) is not None:
            raise ValueError(f"{config.name} arrives with {plan}")
        return config


BASELINE = ModelConfig()


def unbuilt(config: ModelConfig) -> str | None:
    """The plan that builds the config's first missing part, or None when it can run. Every part
    is built today; the seam stays for the next part a plan names before building it."""
    return None


def _factor_names(data: MarketData, config: ModelConfig) -> tuple[str, ...] | None:
    if not config.factors:
        return None
    if data.factors is None:
        raise ValueError(f"{config.name} needs factor columns; load the market with with_factors=True")
    return data.factors.names


def _require_built(config: ModelConfig) -> None:
    if (plan := unbuilt(config)) is not None:
        raise NotImplementedError(f"{config.name} arrives with {plan}")


def run_variant(
    data: MarketData,
    config: ModelConfig,
    train_config: TrainConfig,
    folds: Sequence[Fold] | None = None,
    known_before: pd.Timestamp | None = None,
) -> WalkForward:
    """The variant's out-of-sample walk-forward over `folds` (default: the outer folds)."""
    _require_built(config)
    return walk_forward(
        data, train_config, folds=folds, known_before=known_before, factor_names=_factor_names(data, config),
        ranker=config.ranker, extra_features=data.extras if config.extras else (), bag=config.bagged,
        garch=config.garch,
    )


def fit_variant(data: MarketData, wf: WalkForward, config: ModelConfig, train_config: TrainConfig) -> FinalModel:
    """The variant's final model on every row with a target, calibrated on `wf` (whose run
    decides whether P comes from the ranking booster)."""
    _require_built(config)
    return fit_final(
        data, wf, train_config, factor_names=_factor_names(data, config),
        extra_features=data.extras if config.extras else (), bag=config.bagged, garch=config.garch,
    )
