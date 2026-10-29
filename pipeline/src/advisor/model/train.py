"""Walk-forward training of one market's stock model, its calibration, and its files.

Per horizon: three quantile boosters (the excess-return range) and one binary booster (beats the
benchmark?). The walk-forward predicts each test period with boosters trained only on rows whose
targets ended before it, and calibrates each period on earlier periods' predictions, so every
metric is out of sample. The final model trains on every row with a target.
"""

import gzip
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import isotonic_regression

from advisor.model.dataset import MarketData
from advisor.model.factors import alpha_target, fallback_count
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
    fallback_count: int = 0
    alpha_rank_ic: float | None = None


def _fit(x: pd.DataFrame, y: np.ndarray, config: TrainConfig, **objective) -> lgb.Booster:
    return lgb.train(config.params | objective, lgb.Dataset(x, y), num_boost_round=config.rounds)


def _fit_horizon(
    x: pd.DataFrame, y: pd.Series, config: TrainConfig, beat: pd.Series | None = None
) -> dict[str, lgb.Booster]:
    """Quantile boosters learn `y`. The beat booster learns `beat > 0` when that series is given,
    and `y > 0` otherwise."""
    labels = y if beat is None else beat
    boosters = {
        name: _fit(x, y.to_numpy(), config, objective="quantile", alpha=q)
        for name, q in zip(QUANTILE_NAMES, QUANTILES, strict=True)
    }
    boosters["beat"] = _fit(x, (labels > 0).astype(int).to_numpy(), config, objective="binary")
    return boosters


def _finite_mean(values: pd.Series) -> float:
    mean = float(values.mean())
    return 0.0 if mean != mean else mean


def _factor_shift(frame: pd.DataFrame, names: Sequence[str], mu: Mapping[str, float]) -> np.ndarray:
    """Σ beta·μ, or 0 where any beta is missing."""
    missing = np.zeros(len(frame), dtype=bool)
    shift = np.zeros(len(frame), dtype=float)
    for name in names:
        beta = pd.to_numeric(frame[f"beta_{name}"], errors="coerce").to_numpy(dtype=float)
        bad = ~np.isfinite(beta)
        missing |= bad
        coef = mu.get(name, 0.0)
        if coef is None or coef != coef:
            coef = 0.0
        shift = shift + np.where(bad, 0.0, beta * float(coef))
    return np.where(missing, 0.0, shift)


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


def walk_forward(
    data: MarketData,
    config: TrainConfig = TrainConfig(),  # noqa: B008
    folds: Sequence[Fold] | None = None,
    known_before: pd.Timestamp | None = None,
    factor_names: Sequence[str] | None = None,
) -> WalkForward:
    """Out-of-sample predictions per fold (default: `make_folds`).

    With `known_before`, a fold scores only rows whose target ended before it, so folds nested
    inside a later period's training span never score an outcome from that period.
    With `factor_names`, the quantile boosters learn the factor-adjusted target and the published
    range adds back that fold's mean factor premium. The beat booster still learns `y_h > 0`.
    """
    rows = data.rows
    names = tuple(factor_names or ())
    feat = list(data.features) + [f"beta_{name}" for name in names]
    if folds is None:
        folds = make_folds(pd.DatetimeIndex(rows["day"].unique()), config)
    folds = list(folds)
    frames, metrics = [], {}
    jump = ["jump_5d"] if "jump_5d" in rows else []  # carried so the backtest can skip unconfirmed jumps
    fallbacks = 0
    for h in config.horizons:
        target = f"y_{h}"
        alpha = alpha_target(rows, h, names) if names else None
        parts = []
        for k, fold in enumerate(folds):
            train = training_rows(rows, data.calendar, h, fold.start)
            in_fold = (rows["day"] >= fold.start) & (rows["day"] < fold.end) & rows[target].notna()
            if known_before is not None:
                in_fold &= _ended_before(rows["day"], data.calendar, h, known_before)
            test = rows[in_fold]
            if train.empty or test.empty:  # the last periods of long horizons have no targets yet
                continue
            if names:
                boosters = _fit_horizon(train[feat], alpha.loc[train.index], config, beat=train[target])
                mu = {name: _finite_mean(train[f"f_{name}_{h}"]) for name in names}
            else:
                boosters = _fit_horizon(train[feat], train[target], config)
                mu = {}
            raw = _predict(boosters, test[feat])
            if names:
                q50_alpha = raw["q50"].to_numpy(dtype=float)
                shift = _factor_shift(test, names, mu)
                for quantile in QUANTILE_NAMES:
                    raw[quantile] = raw[quantile].to_numpy(dtype=float) + shift
                raw["q50_alpha"] = q50_alpha
                raw["alpha"] = alpha.loc[test.index].to_numpy(dtype=float)
                fallbacks += fallback_count(test, names)
            out = test[["day", "symbol", "sector", "dollar_volume_20", *jump]].assign(horizon=h, fold=k, y=test[target])
            parts.append(out.join(raw))
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
    extra = ["q50_alpha", "alpha"] if names else []
    columns = ["day", "symbol", "sector", "dollar_volume_20", *jump, "horizon", "fold", "y", *QUANTILE_NAMES, "p_raw", "p", *extra]
    predictions = pd.concat(frames, ignore_index=True)[columns] if frames else pd.DataFrame(columns=columns)
    alpha_ic = None
    if names and not predictions.empty:
        comparable = predictions.dropna(subset=["q50_alpha", "alpha"])
        alpha_ic = rank_ic(comparable, "q50_alpha", "alpha") if not comparable.empty else float("nan")
    return WalkForward(predictions, metrics, folds, fallbacks, alpha_ic)


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
    factor_names: tuple[str, ...] = ()
    mu: dict = field(default_factory=dict)  # horizon → factor → mean forward return
    betas: dict = field(default_factory=dict)  # symbol → factor → latest beta

    def _with_betas(self, x: pd.DataFrame) -> pd.DataFrame:
        if not self.factor_names:
            return x
        frame = x.copy()
        for name in self.factor_names:
            frame[f"beta_{name}"] = [
                self.betas.get(str(symbol), {}).get(name, np.nan) for symbol in frame.index
            ]
        return frame

    def predict(self, x: pd.DataFrame) -> pd.DataFrame:
        """One row per input row per horizon (the input's index), with the range and P(beat)."""
        frame = self._with_betas(x)
        frames = []
        for h in self.horizons:
            out = _predict(self.boosters[h], frame[self.features])
            if self.factor_names:
                shift = _factor_shift(frame, self.factor_names, self.mu.get(h, {}))
                for quantile in QUANTILE_NAMES:
                    out[quantile] = out[quantile].to_numpy(dtype=float) + shift
            out["p_beat"] = self.calibrators[h](out.pop("p_raw").to_numpy())
            out.insert(0, "horizon", h)
            frames.append(out)
        return pd.concat(frames)

    def contributions(self, x: pd.DataFrame, horizon: int, top: int = 3) -> dict[str, list[dict]]:
        """The `top` features that moved each row's median forecast most (by absolute size),
        from LightGBM's per-feature contributions; keyed by the index of `x`. When quantile boosters
        cross, `_predict` sorts them, so the explained booster may not be the displayed q50."""
        frame = self._with_betas(x)
        contrib = self.boosters[horizon]["q50"].predict(frame[self.features], pred_contrib=True)[:, :-1]  # last = bias
        out = {}
        for key, vals in zip(x.index, contrib, strict=True):
            order = np.argsort(-np.abs(vals), kind="stable")[:top]
            out[key] = [{"feature": self.features[i], "contribution": float(vals[i])} for i in order]
        return out

    def screen(self, x: pd.DataFrame) -> np.ndarray:
        """Uncalibrated price-only score: it only ranks, to shortlist stocks for a full prediction."""
        return self.screener.predict(x[self.screener_features])


def _latest_betas(rows: pd.DataFrame, names: Sequence[str]) -> dict[str, dict[str, float | None]]:
    """Each symbol's betas on its latest row. A missing beta is stored as None."""
    last = rows.sort_values("day", kind="stable").groupby("symbol", sort=False).tail(1)
    out: dict[str, dict[str, float | None]] = {}
    for row in last.itertuples(index=False):
        stored: dict[str, float | None] = {}
        for name in names:
            value = getattr(row, f"beta_{name}")
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = float("nan")
            stored[name] = None if number != number else number
        out[str(row.symbol)] = stored
    return out


def fit_final(
    data: MarketData,
    wf: WalkForward,
    config: TrainConfig = TrainConfig(),  # noqa: B008
    factor_names: Sequence[str] | None = None,
) -> FinalModel:
    rows = data.rows
    names = tuple(factor_names or ())
    feat = list(data.features) + [f"beta_{name}" for name in names]
    boosters, calibrators = {}, {}
    for h in config.horizons:
        oos = wf.predictions[(wf.predictions["horizon"] == h) & (wf.predictions["fold"] > 0)]
        if oos.empty:
            raise ValueError(f"no out-of-sample predictions to calibrate horizon {h} on")
        calibrators[h] = Calibrator.fit(oos["p_raw"].to_numpy(), (oos["y"] > 0).to_numpy())
        train = rows[rows[f"y_{h}"].notna()]
        if names:
            boosters[h] = _fit_horizon(train[feat], alpha_target(train, h, names), config, beat=train[f"y_{h}"])
        else:
            boosters[h] = _fit_horizon(train[feat], train[f"y_{h}"], config)
    screener_features = PRICE_FEATURES + RS_FEATURES
    if not set(screener_features) <= set(data.features):  # coins have no sector features
        screener_features = list(data.features)
    # the 21-session target, or (for coins, whose horizons are days) the horizon nearest it
    horizon = SCREENER_HORIZON
    if f"y_{horizon}" not in rows:
        horizon = min(config.horizons, key=lambda h: (abs(h - SCREENER_HORIZON), h))
    train = rows[rows[f"y_{horizon}"].notna()]
    beat = (train[f"y_{horizon}"] > 0).astype(int).to_numpy()
    screener = _fit(train[screener_features], beat, config, objective="binary")
    mu = {
        h: {name: _finite_mean(rows.loc[rows[f"y_{h}"].notna(), f"f_{name}_{h}"]) for name in names}
        for h in config.horizons
    } if names else {}
    betas = _latest_betas(rows, names) if names else {}
    return FinalModel(
        feat, tuple(config.horizons), boosters, calibrators, screener, screener_features,
        dict(config.params), config.rounds, names, mu, betas,
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
    if model.factor_names:
        files["factors"] = _pack(json.dumps({
            "names": list(model.factor_names),
            "mu": {str(h): dict(values) for h, values in model.mu.items()},
            "betas": model.betas,
        }))
    return files


def from_files(files: Mapping[str, bytes]) -> FinalModel:
    meta = json.loads(_unpack(files["meta"]))
    horizons = tuple(meta["horizons"])
    calibration = json.loads(_unpack(files["calibration"]))

    def booster(name: str) -> lgb.Booster:
        return lgb.Booster(model_str=_unpack(files[name]))

    stored = json.loads(_unpack(files["factors"])) if "factors" in files else None
    if stored:
        factor_names = tuple(stored["names"])
        mu = {int(h): {name: float(value) for name, value in values.items()} for h, values in stored["mu"].items()}
        betas = {
            symbol: {name: (np.nan if value is None else float(value)) for name, value in values.items()}
            for symbol, values in stored["betas"].items()
        }
    else:
        factor_names, mu, betas = (), {}, {}
    return FinalModel(
        meta["features"], horizons,
        {h: {part: booster(f"h{h}_{part}") for part in PARTS} for h in horizons},
        {h: Calibrator.from_json(calibration[str(h)]) for h in horizons},
        booster("screener"), meta["screener_features"], meta["params"], meta["rounds"],
        factor_names, mu, betas,
    )
