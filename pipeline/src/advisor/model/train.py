"""Walk-forward training of one market's stock model, its calibration, and its files.

Per horizon: three quantile boosters (the excess-return range) and one binary booster (beats the
benchmark?). The walk-forward predicts each test period with boosters trained only on rows whose
targets ended before it, and calibrates each period on earlier periods' predictions, so every
metric is out of sample. The final model trains on every row with a target.
"""

import gzip
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import isotonic_regression

from advisor.model.dataset import MarketData
from advisor.model.features import HORIZONS, PRICE_FEATURES, RS_FEATURES

QUANTILES = (0.1, 0.5, 0.9)
PARAMS = {
    "learning_rate": 0.075, "num_leaves": 31, "min_data_in_leaf": 500, "feature_fraction": 0.8,
    "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0, "seed": 7, "verbose": -1,
}
MIN_BIN = 500  # rows per bin that set the calibration's floor and ceiling
SCREENER_HORIZON = 21
QUANTILE_NAMES = tuple(f"q{round(q * 100)}" for q in QUANTILES)
PARTS = (*QUANTILE_NAMES, "beat")


@dataclass(frozen=True)
class TrainConfig:
    horizons: tuple[int, ...] = HORIZONS
    rounds: int = 200
    folds: int = 4
    min_train_years: float = 2.0
    params: dict = field(default_factory=lambda: dict(PARAMS))


@dataclass(frozen=True)
class Fold:
    start: pd.Timestamp
    end: pd.Timestamp  # exclusive


def make_folds(days: pd.DatetimeIndex, config: TrainConfig) -> list[Fold]:
    """Equal test periods after `min_train_years` of history, the last ending after `days`."""
    first = days.min() + pd.DateOffset(months=round(config.min_train_years * 12))
    end = days.max() + pd.Timedelta(days=1)
    if first >= end:
        raise ValueError(f"under {config.min_train_years} years of history: nothing to test on")
    edges = pd.date_range(first, end, periods=config.folds + 1)
    return [Fold(a, b) for a, b in zip(edges[:-1], edges[1:], strict=True)]


def training_rows(
    rows: pd.DataFrame, calendar: pd.DatetimeIndex, horizon: int, start: pd.Timestamp
) -> pd.DataFrame:
    """Rows whose `horizon`-session target ended before `start` (the embargo)."""
    return rows[_ended_before(rows["day"], calendar, horizon, start) & rows[f"y_{horizon}"].notna().to_numpy()]


def _ended_before(
    days: pd.Series, calendar: pd.DatetimeIndex, horizon: int, start: pd.Timestamp
) -> np.ndarray:
    """Whether a target starting on each day was known before `start`, the first session on or after it."""
    start_pos = calendar.searchsorted(start, side="left")
    return calendar.searchsorted(pd.DatetimeIndex(days), side="left") + horizon < start_pos


class Calibrator:
    """Isotonic map from the classifier's score to a beat probability.

    Clipped to the lowest and highest hit rate of `MIN_BIN`-row bins: a handful of lucky extreme
    scores must not turn into a promise the bulk of the data doesn't support.
    """

    def __init__(self, xs: np.ndarray, ys: np.ndarray, lo: float, hi: float):
        self.xs, self.ys, self.lo, self.hi = np.asarray(xs, float), np.asarray(ys, float), lo, hi

    @classmethod
    def fit(cls, p_raw: np.ndarray, beat: np.ndarray, min_bin: int = MIN_BIN) -> "Calibrator":
        p_raw, beat = np.asarray(p_raw, float), np.asarray(beat, float)
        if len(p_raw) == 0:
            raise ValueError("no predictions to calibrate on")
        xs, inverse, counts = np.unique(p_raw, return_inverse=True, return_counts=True)
        ys = isotonic_regression(np.bincount(inverse, weights=beat) / counts, weights=counts).x
        # the fit is a step function: each step's two ends interpolate it exactly
        keep = np.ones(len(ys), dtype=bool)
        keep[1:-1] = (ys[1:-1] != ys[:-2]) | (ys[1:-1] != ys[2:])
        bins = np.array_split(np.argsort(p_raw, kind="stable"), min(20, max(1, len(p_raw) // min_bin)))
        rates = [beat[b].mean() for b in bins]
        return cls(xs[keep], ys[keep], float(min(rates)), float(max(rates)))

    def __call__(self, p_raw: np.ndarray) -> np.ndarray:
        return np.clip(np.interp(np.asarray(p_raw, float), self.xs, self.ys), self.lo, self.hi)

    def to_json(self) -> dict:
        return {"xs": self.xs.tolist(), "ys": self.ys.tolist(), "lo": self.lo, "hi": self.hi}

    @classmethod
    def from_json(cls, d: Mapping) -> "Calibrator":
        return cls(np.array(d["xs"]), np.array(d["ys"]), d["lo"], d["hi"])


def _bin_gaps(p: np.ndarray, beat: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray]:
    p, beat = np.asarray(p, float), np.asarray(beat, float)
    parts = [b for b in np.array_split(np.argsort(p, kind="stable"), bins) if len(b)]
    gaps = np.array([abs(p[b].mean() - beat[b].mean()) for b in parts]) * 100
    return gaps, np.array([len(b) for b in parts])


def calibration_error(p: np.ndarray, beat: np.ndarray, bins: int = 10) -> float:
    """Count-weighted mean over equal-count bins of |mean p - hit rate|, in percentage points."""
    gaps, weights = _bin_gaps(p, beat, bins)
    return float(np.average(gaps, weights=weights))


def rank_ic(frame: pd.DataFrame, pred: str, actual: str) -> float:
    """Mean over days of the Spearman correlation between `pred` and `actual`."""
    per_day = [g[pred].rank().corr(g[actual].rank()) for _, g in frame.groupby("day")]
    return float(pd.Series(per_day, dtype=float).mean())


@dataclass
class WalkForward:
    predictions: pd.DataFrame
    metrics: dict[int, dict]
    folds: list[Fold] = field(default_factory=list)


def _fit(x: pd.DataFrame, y: np.ndarray, config: TrainConfig, **objective) -> lgb.Booster:
    return lgb.train(config.params | objective, lgb.Dataset(x, y), num_boost_round=config.rounds)


def _fit_horizon(x: pd.DataFrame, y: pd.Series, config: TrainConfig) -> dict[str, lgb.Booster]:
    boosters = {
        name: _fit(x, y.to_numpy(), config, objective="quantile", alpha=q)
        for name, q in zip(QUANTILE_NAMES, QUANTILES, strict=True)
    }
    boosters["beat"] = _fit(x, (y > 0).astype(int).to_numpy(), config, objective="binary")
    return boosters


def _predict(boosters: Mapping[str, lgb.Booster], x: pd.DataFrame) -> pd.DataFrame:
    # boosters fitted separately can cross; a range must still read low <= mid <= high
    quantiles = np.sort(np.column_stack([boosters[name].predict(x) for name in QUANTILE_NAMES]), axis=1)
    out = pd.DataFrame(quantiles, index=x.index, columns=list(QUANTILE_NAMES))
    out["p_raw"] = boosters["beat"].predict(x)
    return out


def _metrics(scored: pd.DataFrame) -> dict:
    beat = (scored["y"] > 0).to_numpy()
    gaps, weights = _bin_gaps(scored["p"].to_numpy(), beat, 10)
    inside = (scored["y"] >= scored["q10"]) & (scored["y"] <= scored["q90"])
    return {
        "calibration_pts": float(np.average(gaps, weights=weights)),
        "max_bin_gap_pts": float(gaps.max()),
        "rank_ic": rank_ic(scored, "q50", "y"),
        "coverage_10_90": float(inside.mean()),
        "base_rate": float(beat.mean()),
    }


def walk_forward(data: MarketData, config: TrainConfig = TrainConfig()) -> WalkForward:  # noqa: B008
    rows = data.rows
    folds = make_folds(pd.DatetimeIndex(rows["day"].unique()), config)
    frames, metrics = [], {}
    jump = ["jump_5d"] if "jump_5d" in rows else []  # carried so the backtest can skip unconfirmed jumps
    for h in config.horizons:
        target = f"y_{h}"
        parts = []
        for k, fold in enumerate(folds):
            train = training_rows(rows, data.calendar, h, fold.start)
            test = rows[(rows["day"] >= fold.start) & (rows["day"] < fold.end) & rows[target].notna()]
            if train.empty or test.empty:  # the last periods of long horizons have no targets yet
                continue
            boosters = _fit_horizon(train[data.features], train[target], config)
            out = test[["day", "symbol", "sector", "dollar_volume_20", *jump]].assign(horizon=h, fold=k, y=test[target])
            parts.append(out.join(_predict(boosters, test[data.features])))
        if not parts:
            continue
        pred = pd.concat(parts, ignore_index=True)
        pred["p"] = np.nan
        for k in pred["fold"].unique():
            # earlier predictions whose outcome was known when this period began
            earlier = pred[_ended_before(pred["day"], data.calendar, h, folds[k].start)]
            if earlier.empty:  # nothing out of sample to calibrate this period on
                continue
            calibrator = Calibrator.fit(earlier["p_raw"].to_numpy(), (earlier["y"] > 0).to_numpy())
            here = pred["fold"] == k
            pred.loc[here, "p"] = calibrator(pred.loc[here, "p_raw"].to_numpy())
        frames.append(pred)
        scored = pred[pred["p"].notna()]
        if not scored.empty:
            metrics[h] = _metrics(scored)
    columns = ["day", "symbol", "sector", "dollar_volume_20", *jump, "horizon", "fold", "y", *QUANTILE_NAMES, "p_raw", "p"]
    predictions = pd.concat(frames, ignore_index=True)[columns] if frames else pd.DataFrame(columns=columns)
    return WalkForward(predictions, metrics, folds)


@dataclass(frozen=True)
class FinalModel:
    features: list[str]
    horizons: tuple[int, ...]
    boosters: dict[int, dict[str, lgb.Booster]]
    calibrators: dict[int, Calibrator]
    screener: lgb.Booster
    screener_features: list[str]
    params: dict
    rounds: int

    def predict(self, x: pd.DataFrame) -> pd.DataFrame:
        """One row per input row per horizon (the input's index), with the range and P(beat)."""
        frames = []
        for h in self.horizons:
            out = _predict(self.boosters[h], x[self.features])
            out["p_beat"] = self.calibrators[h](out.pop("p_raw").to_numpy())
            out.insert(0, "horizon", h)
            frames.append(out)
        return pd.concat(frames)

    def screen(self, x: pd.DataFrame) -> np.ndarray:
        """Uncalibrated price-only score: it only ranks, to shortlist stocks for a full prediction."""
        return self.screener.predict(x[self.screener_features])


def fit_final(data: MarketData, wf: WalkForward, config: TrainConfig = TrainConfig()) -> FinalModel:  # noqa: B008
    rows = data.rows
    boosters, calibrators = {}, {}
    for h in config.horizons:
        oos = wf.predictions[(wf.predictions["horizon"] == h) & (wf.predictions["fold"] > 0)]
        if oos.empty:
            raise ValueError(f"no out-of-sample predictions to calibrate horizon {h} on")
        calibrators[h] = Calibrator.fit(oos["p_raw"].to_numpy(), (oos["y"] > 0).to_numpy())
        train = rows[rows[f"y_{h}"].notna()]
        boosters[h] = _fit_horizon(train[data.features], train[f"y_{h}"], config)
    screener_features = PRICE_FEATURES + RS_FEATURES
    train = rows[rows[f"y_{SCREENER_HORIZON}"].notna()]
    beat = (train[f"y_{SCREENER_HORIZON}"] > 0).astype(int).to_numpy()
    screener = _fit(train[screener_features], beat, config, objective="binary")
    return FinalModel(
        list(data.features), tuple(config.horizons), boosters, calibrators, screener, screener_features,
        dict(config.params), config.rounds,
    )


def _pack(value: str) -> bytes:
    return gzip.compress(value.encode())


def _unpack(blob: bytes) -> str:
    return gzip.decompress(blob).decode()


def to_files(model: FinalModel) -> dict[str, bytes]:
    files = {
        f"h{h}_{part}": _pack(model.boosters[h][part].model_to_string())
        for h in model.horizons for part in PARTS
    }
    files["screener"] = _pack(model.screener.model_to_string())
    files["calibration"] = _pack(json.dumps({str(h): c.to_json() for h, c in model.calibrators.items()}))
    files["meta"] = _pack(json.dumps({
        "features": model.features, "screener_features": model.screener_features,
        "horizons": list(model.horizons), "params": model.params, "rounds": model.rounds,
    }))
    return files


def from_files(files: Mapping[str, bytes]) -> FinalModel:
    meta = json.loads(_unpack(files["meta"]))
    horizons = tuple(meta["horizons"])
    calibration = json.loads(_unpack(files["calibration"]))

    def booster(name: str) -> lgb.Booster:
        return lgb.Booster(model_str=_unpack(files[name]))

    return FinalModel(
        meta["features"], horizons,
        {h: {part: booster(f"h{h}_{part}") for part in PARTS} for h in horizons},
        {h: Calibrator.from_json(calibration[str(h)]) for h in horizons},
        booster("screener"), meta["screener_features"], meta["params"], meta["rounds"],
    )
