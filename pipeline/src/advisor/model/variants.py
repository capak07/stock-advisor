"""A model configuration (a variant), and the one seam every variant trains through.

The benchmark compares variants on identical folds; weekly training runs the market's accepted
one. Plan 6a builds only the baseline: factors (Plan 6c) and GARCH (Plan 6d) are named here
so stored configurations and reports can refer to them, but running one before its plan lands
is refused, never silently treated as the baseline. A tuned policy is a `Policy` value.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from advisor.model.dataset import MarketData
from advisor.model.train import FinalModel, Fold, TrainConfig, WalkForward, fit_final, walk_forward
from advisor.policy import Policy

CONFIG_VERSION = 1
_KEYS = {"version", "factors", "garch", "policy"}


@dataclass(frozen=True)
class ModelConfig:
    factors: bool = False
    garch: bool = False
    policy: Policy | None = None  # tuned rules; None = today's constants

    @property
    def name(self) -> str:
        model = "+".join(part for part, on in (("factors", self.factors), ("garch", self.garch)) if on)
        return (model or "baseline") + ("+policy" if self.policy is not None else "")

    def to_json(self) -> dict[str, Any]:
        policy = None if self.policy is None else self.policy.to_json()
        return {"version": CONFIG_VERSION, "factors": self.factors, "garch": self.garch, "policy": policy}

    @classmethod
    def from_json(cls, d: Any) -> "ModelConfig":
        """A stored configuration, refused (ValueError) unless this code can run it as written."""
        if not isinstance(d, Mapping):
            raise ValueError(f"a stored config must be a mapping, not {type(d).__name__}")
        if set(d) != _KEYS:
            odd = sorted(set(d) ^ _KEYS)
            raise ValueError(f"a stored config has unexpected or missing keys: {', '.join(odd)}")
        if d["version"] != CONFIG_VERSION:
            raise ValueError(f"unknown config version {d['version']!r}")
        raw = d["policy"]
        policy = None if raw is None else Policy.from_json(raw)
        config = cls(bool(d["factors"]), bool(d["garch"]), policy)
        if (plan := unbuilt(config)) is not None:
            raise ValueError(f"{config.name} arrives with {plan}")
        return config


BASELINE = ModelConfig()


def unbuilt(config: ModelConfig) -> str | None:
    """The plan that builds the config's first missing part, or None when it can run."""
    if config.factors:
        return "Plan 6c"
    if config.garch:
        return "Plan 6d"
    return None


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
    return walk_forward(data, train_config, folds=folds, known_before=known_before)


def fit_variant(data: MarketData, wf: WalkForward, config: ModelConfig, train_config: TrainConfig) -> FinalModel:
    """The variant's final model on every row with a target, calibrated on `wf`."""
    _require_built(config)
    return fit_final(data, wf, train_config)
