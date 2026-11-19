"""A model configuration (a variant), and the one seam every variant trains through.

The benchmark compares variants on identical folds; weekly training runs the market's accepted
one. `garch` (Plan 6d) trains each horizon on its GARCH forecast volatility (spec §4); the data
must be loaded with `with_garch=True`. A tuned policy is a `Policy` value. `ranker` (Plan 6f) swaps the beat classifier for a ranking booster (spec §8).
`extras` adds the market's extra features and `bagged` averages three seeds per booster (spec §9).
`earnings` (Plan 6k) adds the US quarterly earnings features. `forest` (spec 2026-11-15) makes the
ranking booster a random forest; it needs `ranker`. `short`, `analyst`, `insider`, `events`, `holders`,
`estimates` and `catalysts` (Plan 7b) each add one US data group's features; a config whose group the
data build did not write is refused by name (`missing_groups`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from advisor.model.dataset import MarketData
from advisor.model.groups import DATA_GROUPS, GROUP_FEATURES, LETTERS
from advisor.model.train import FinalModel, Fold, TrainConfig, WalkForward, fit_final, walk_forward
from advisor.policy import Policy

CONFIG_VERSION = 6
# version 1 (before Plan 6f) had no `ranker`, version 2 (before Plan 6g) no `extras` or `bagged`;
# version 3 (before Plan 6k) no `earnings`, version 4 (before 2026-11-15) no `forest`, version 5 (before
# Plan 7b) none of the seven new data groups; all still load, with those parts off
_KEYS = {
    1: {"version", "factors", "garch", "policy"},
    2: {"version", "factors", "garch", "ranker", "policy"},
    3: {"version", "factors", "garch", "ranker", "extras", "bagged", "policy"},
    4: {"version", "factors", "garch", "ranker", "extras", "bagged", "earnings", "policy"},
    5: {"version", "factors", "garch", "ranker", "forest", "extras", "bagged", "earnings", "policy"},
}
_NEW_GROUPS = ("short", "analyst", "insider", "events", "holders", "estimates", "catalysts")
_KEYS[6] = _KEYS[5] | set(_NEW_GROUPS)
MAX_NAME = 40  # supabase/migrations/0010_benchmarks.sql: variant names match ^[a-z+]{1,40}$


@dataclass(frozen=True)
class ModelConfig:
    factors: bool = False
    garch: bool = False
    policy: Policy | None = None  # tuned rules; None = today's constants
    ranker: bool = False
    extras: bool = False
    bagged: bool = False
    earnings: bool = False
    forest: bool = False
    short: bool = False
    analyst: bool = False
    insider: bool = False
    events: bool = False
    holders: bool = False
    estimates: bool = False
    catalysts: bool = False

    @property
    def name(self) -> str:
        head = [part for part, on in (("factors", self.factors), ("garch", self.garch), ("ranker", self.ranker),
                                      ("forest", self.forest), ("extras", self.extras)) if on]
        groups = list(data_groups(self))
        tail = ["bagged"] if self.bagged else []
        model = "+".join(head + groups + tail)
        if len(model) > MAX_NAME:  # the groups become `data` and one letter each
            model = "+".join(head + ["data", *(LETTERS[group] for group in groups)] + tail)
        return (model or "baseline") + ("+policy" if self.policy is not None else "")

    def to_json(self) -> dict[str, Any]:
        policy = None if self.policy is None else self.policy.to_json()
        return {
            "version": CONFIG_VERSION, "factors": self.factors, "garch": self.garch, "ranker": self.ranker,
            "forest": self.forest, "extras": self.extras, "bagged": self.bagged, "earnings": self.earnings,
            **{group: getattr(self, group) for group in _NEW_GROUPS}, "policy": policy,
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
        flags = {key: bool(d.get(key, False)) for key in
                 ("ranker", "extras", "bagged", "earnings", "forest", *_NEW_GROUPS)}
        config = cls(factors=bool(d["factors"]), garch=bool(d["garch"]), policy=policy, **flags)
        if config.forest and not config.ranker:
            raise ValueError(f"{config.name}: a forest is a ranking booster, so it needs the ranker")
        if (plan := unbuilt(config)) is not None:
            raise ValueError(f"{config.name} arrives with {plan}")
        return config


BASELINE = ModelConfig()


def data_groups(config: ModelConfig) -> tuple[str, ...]:
    """The data groups the config turns on, in `DATA_GROUPS` order."""
    return tuple(group for group in DATA_GROUPS if getattr(config, group))


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


def missing_groups(data: MarketData, config: ModelConfig) -> list[str]:
    """The data groups the config needs that `data.groups` lacks (the build did not write their history)."""
    return [group for group in data_groups(config) if group not in data.groups]


def extra_features(data: MarketData, config: ModelConfig) -> tuple[str, ...]:
    """The optional columns of `data` the config trains on: the market's extras with `extras`, and each
    data group's features for each group that is on, in the data's order. A group the build did not
    write is refused by name."""
    if missing := missing_groups(data, config):
        raise ValueError(f"{config.name} needs the {missing[0]} data, which this build did not write")
    wanted = {name for group in data_groups(config) for name in GROUP_FEATURES[group]}
    grouped = {name for names in GROUP_FEATURES.values() for name in names}
    return tuple(f for f in data.extras if (f in wanted if f in grouped else config.extras))


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
        ranker=config.ranker, extra_features=extra_features(data, config), bag=config.bagged,
        garch=config.garch, forest=config.forest,
    )


def fit_variant(data: MarketData, wf: WalkForward, config: ModelConfig, train_config: TrainConfig) -> FinalModel:
    """The variant's final model on every row with a target, calibrated on `wf` (whose run
    decides whether P comes from the ranking booster)."""
    _require_built(config)
    return fit_final(
        data, wf, train_config, factor_names=_factor_names(data, config),
        extra_features=extra_features(data, config), bag=config.bagged, garch=config.garch,
    )
