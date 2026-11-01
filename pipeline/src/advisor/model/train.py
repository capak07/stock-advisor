"""Walk-forward training of one market's stock model, its calibration, and its files.

Per horizon: three quantile boosters (the excess-return range) and one booster whose calibrated
score is P(beat): a binary classifier (beats the benchmark?) or, with the ranker (spec §8), a
booster that learns each stock's rank among that day's stocks. The walk-forward predicts each test period with boosters trained only on rows whose
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
# the ranking booster learns slower than the others; laid over the train config's params (spec §8)
RANK_SETTINGS = {"learning_rate": 0.03, "num_leaves": 15}
RANK_ROUNDS = 400


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

    Clipped between the hit rates of the lowest- and highest-scored `MIN_BIN`-row bins: a handful of
    lucky extreme scores must not turn into a promise the bulk of the data doesn't support. When the
    score ran backwards (the lowest-scored bin beat more often than the highest), every score gets
    the overall rate: the score told nothing about beating the benchmark.
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
        # in score order: the best bin anywhere is no ceiling for the top scores. On US 63- and
        # 126-day data the lowest-scored bin beat most often, and its rate capped two lucky
        # top-scored rows at a 59% promise that 11-33% of picks then delivered
        lo, hi = float(beat[bins[0]].mean()), float(beat[bins[-1]].mean())
        if lo > hi:
            lo = hi = float(beat.mean())
        return cls(xs[keep], ys[keep], lo, hi)

    def __call__(self, p_raw: np.ndarray) -> np.ndarray:
        return np.clip(np.interp(np.asarray(p_raw, float), self.xs, self.ys), self.lo, self.hi)

    def to_json(self) -> dict:
        return {"xs": self.xs.tolist(), "ys": self.ys.tolist(), "lo": self.lo, "hi": self.hi}

    @classmethod
    def from_json(cls, d: Mapping) -> "Calibrator":
        return cls(np.array(d["xs"]), np.array(d["ys"]), d["lo"], d["hi"])


class RangeCalibrator:
    """Moves each edge of a forecast range so that, on earlier out-of-sample outcomes, a tenth, half
    and nine tenths of outcomes fell below q10, q50 and q90.

    The quantile boosters are never checked against outcomes the way P(beat) is, and on real data
    their median leans high (a +19% median beside a 46% chance of beating the benchmark). Each shift
    is in units of the range's width, so a wide, volatile range moves further than a narrow one.
    Only the edges in `shifts` move; the others keep the boosters' value.
    """

    def __init__(self, shifts: Mapping[str, float]):
        unknown = set(shifts) - set(QUANTILE_NAMES)
        if unknown:
            raise ValueError(f"not a range edge: {sorted(unknown)}")
        self.shifts = {name: float(shifts[name]) for name in QUANTILE_NAMES if name in shifts}

    @classmethod
    def fit(cls, pred: pd.DataFrame, names: Sequence[str] = QUANTILE_NAMES) -> "RangeCalibrator":
        width = _width(pred)
        y = pred["y"].to_numpy(dtype=float)
        return cls({
            name: float(np.quantile((y - pred[name].to_numpy(dtype=float)) / width, q))
            for name, q in zip(QUANTILE_NAMES, QUANTILES, strict=True) if name in names
        })

    def __call__(self, quantiles: pd.DataFrame) -> pd.DataFrame:
        width = _width(quantiles)
        moved = np.column_stack([
            quantiles[name].to_numpy(dtype=float) + self.shifts.get(name, 0.0) * width for name in QUANTILE_NAMES
        ])
        return pd.DataFrame(np.sort(moved, axis=1), index=quantiles.index, columns=list(QUANTILE_NAMES))

    def to_json(self) -> dict:
        return dict(self.shifts)

    @classmethod
    def from_json(cls, d: Mapping) -> "RangeCalibrator":
        return cls(d)


MIN_WIDTH = 1e-4  # a range with no width still moves, by a tiny amount
RAW_NAMES = tuple(f"{name}_raw" for name in QUANTILE_NAMES)


def _width(quantiles: pd.DataFrame) -> np.ndarray:
    return np.maximum((quantiles["q90"] - quantiles["q10"]).to_numpy(dtype=float), MIN_WIDTH)


def pinball_loss(y: np.ndarray, q: np.ndarray, alpha: float) -> float:
    """Mean pinball loss at `alpha`: over- and under-shoots are weighted by the quantile."""
    d = np.asarray(y, float) - np.asarray(q, float)
    return float(np.mean(np.maximum(alpha * d, (alpha - 1) * d)))


def _edge_pinball(frame: pd.DataFrame, columns: Sequence[str]) -> dict[str, float]:
    """Each edge's pinball loss at its own quantile, keyed by edge name."""
    y = frame["y"].to_numpy(dtype=float)
    return {
        name: pinball_loss(y, frame[c].to_numpy(dtype=float), q)
        for name, c, q in zip(QUANTILE_NAMES, columns, QUANTILES, strict=True)
    }


def _as_range(frame: pd.DataFrame, names: Sequence[str]) -> pd.DataFrame:
    return frame[list(names)].set_axis(list(QUANTILE_NAMES), axis=1)


def calibrate_ranges(
    pred: pd.DataFrame, calendar: pd.DatetimeIndex, horizon: int, folds: Sequence[Fold]
) -> tuple[pd.DataFrame, dict]:
    """One horizon's predictions with each period's range calibrated on outcomes known before it.

    Each edge (q10, q50, q90) is judged on its own: a period uses an edge's calibrated value only if
    it beat the raw one, by that edge's pinball loss, on earlier periods whose outcomes were known
    when it began; so neither the shift nor the choice to use it sees the period's own outcomes. On
    real data the edges were too narrow while the median was already centred, so correcting all
    three together fixed the edges and pushed the median off. The raw range stays in `q*_raw`.
    `info["adopted"]` is the same test, per edge, over every calibrated period: what the final
    model, fitted on all of them, follows.
    """
    out = pred.copy()
    for name, raw in zip(QUANTILE_NAMES, RAW_NAMES, strict=True):
        out[raw] = out[name].to_numpy(dtype=float)
    calibrated = pd.DataFrame(np.nan, index=out.index, columns=list(QUANTILE_NAMES))
    used: dict[int, dict[str, bool]] = {}
    for k in sorted(out["fold"].unique()):
        known = _ended_before(out["day"], calendar, horizon, folds[int(k)].start)
        earlier = out[known]
        if earlier.empty:  # nothing out of sample to calibrate this period on
            continue
        here = out["fold"] == k
        fitted = RangeCalibrator.fit(_as_range(earlier, RAW_NAMES).assign(y=earlier["y"]))
        calibrated.loc[here] = fitted(_as_range(out.loc[here], RAW_NAMES)).to_numpy()
        evidence = known & calibrated["q50"].notna() & ~here
        none = dict.fromkeys(QUANTILE_NAMES, False)
        used[int(k)] = _calibration_helps(out[evidence], calibrated[evidence]) if evidence.any() else none
        chosen = [name for name in QUANTILE_NAMES if used[int(k)][name]]
        if chosen:
            for name in chosen:
                out.loc[here, name] = calibrated.loc[here, name]
            # a moved edge can pass one left raw; a range must still read low <= mid <= high
            edges = list(QUANTILE_NAMES)
            out.loc[here, edges] = np.sort(out.loc[here, edges].to_numpy(dtype=float), axis=1)
    scored = calibrated["q50"].notna()
    info = {"adopted": dict.fromkeys(QUANTILE_NAMES, False), "periods": {str(k): v for k, v in used.items()},
            "pinball_raw": None, "pinball_calibrated": None, "below_median_raw": None,
            "below_median_calibrated": None}
    if scored.any():
        both = out.loc[scored, ["y", *RAW_NAMES]].join(calibrated.loc[scored])
        info["pinball_raw"] = _edge_pinball(both, RAW_NAMES)
        info["pinball_calibrated"] = _edge_pinball(both, QUANTILE_NAMES)
        info["below_median_raw"] = float((both["y"] < both["q50_raw"]).mean())
        info["below_median_calibrated"] = float((both["y"] < both["q50"]).mean())
        info["adopted"] = _calibration_helps(out[scored], calibrated[scored])
    return out, info


def _calibration_helps(raw: pd.DataFrame, calibrated: pd.DataFrame) -> dict[str, bool]:
    """Per edge, whether its calibrated value had a lower pinball loss than the raw one on these rows."""
    both = raw[["y", *RAW_NAMES]].join(calibrated)
    before, after = _edge_pinball(both, RAW_NAMES), _edge_pinball(both, QUANTILE_NAMES)
    return {name: bool(after[name] < before[name]) for name in QUANTILE_NAMES}  # a NaN never is


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


def rank_ic_by_horizon(frame: pd.DataFrame, pred: str, actual: str) -> float:
    """`rank_ic` within each horizon, averaged: ranking 5-day and 126-day values together would
    reward a forecast for knowing that longer horizons move more."""
    per_horizon = [rank_ic(g, pred, actual) for _, g in frame.groupby("horizon")]
    return float(pd.Series(per_horizon, dtype=float).mean())


@dataclass
class WalkForward:
    predictions: pd.DataFrame
    metrics: dict[int, dict]
    folds: list[Fold] = field(default_factory=list)
    fallback_count: int = 0
    alpha_rank_ic: float | None = None
    ranker: bool = False  # P and `score` come from the ranking booster


def daily_rank(rows: pd.DataFrame, target: str) -> pd.Series:
    """Each row's percentile rank of `target` among that day's rows, minus 0.5; NaN stays NaN.

    Only the same day's targets enter a row's rank, and they all end on the same session, so the
    rank is known exactly when the row's own target is.
    """
    return rows[target].groupby(rows["day"]).rank(pct=True, method="average") - 0.5


def _fit(x: pd.DataFrame, y: np.ndarray, config: TrainConfig, **objective) -> lgb.Booster:
    return lgb.train(config.params | objective, lgb.Dataset(x, y), num_boost_round=config.rounds)


def _fit_horizon(
    x: pd.DataFrame, y: pd.Series, config: TrainConfig, beat: pd.Series | None = None,
    rank: pd.Series | None = None,
) -> dict[str, lgb.Booster]:
    """Quantile boosters learn `y`. With `rank`, a ranking booster learns it in place of the beat
    booster; otherwise the beat booster learns `beat > 0` when that series is given, and `y > 0`
    otherwise."""
    labels = y if beat is None else beat
    boosters = {
        name: _fit(x, y.to_numpy(), config, objective="quantile", alpha=q)
        for name, q in zip(QUANTILE_NAMES, QUANTILES, strict=True)
    }
    if rank is not None:
        params = config.params | RANK_SETTINGS | {"objective": "quantile", "alpha": 0.5}
        boosters["rank"] = lgb.train(params, lgb.Dataset(x, rank.to_numpy()), num_boost_round=RANK_ROUNDS)
    else:
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
    out["p_raw"] = boosters["rank" if "rank" in boosters else "beat"].predict(x)
    return out


def _metrics(scored: pd.DataFrame) -> dict:
    beat = (scored["y"] > 0).to_numpy()
    gaps, weights = _bin_gaps(scored["p"].to_numpy(), beat, 10)
    inside = (scored["y"] >= scored["q10"]) & (scored["y"] <= scored["q90"])
    return {
        "calibration_pts": float(np.average(gaps, weights=weights)),
        "max_bin_gap_pts": float(gaps.max()),
        "rank_ic": rank_ic(scored, "score", "y"),
        "coverage_10_90": float(inside.mean()),
        "base_rate": float(beat.mean()),
    }


def walk_forward(
    data: MarketData,
    config: TrainConfig = TrainConfig(),  # noqa: B008
    folds: Sequence[Fold] | None = None,
    known_before: pd.Timestamp | None = None,
    factor_names: Sequence[str] | None = None,
    ranker: bool = False,
) -> WalkForward:
    """Out-of-sample predictions per fold (default: `make_folds`).

    With `known_before`, a fold scores only rows whose target ended before it, so folds nested
    inside a later period's training span never score an outcome from that period.
    With `factor_names`, the quantile boosters learn the factor-adjusted target and the published
    range adds back that fold's mean factor premium. The beat booster still learns `y_h > 0`.
    With `ranker`, a ranking booster learns `daily_rank` in place of the beat booster, and its
    score ranks (`score`) and is calibrated into P. Otherwise `score` is the published q50.
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
        rank = daily_rank(rows, target) if ranker else None
        parts = []
        for k, fold in enumerate(folds):
            train = training_rows(rows, data.calendar, h, fold.start)
            in_fold = (rows["day"] >= fold.start) & (rows["day"] < fold.end) & rows[target].notna()
            if known_before is not None:
                in_fold &= _ended_before(rows["day"], data.calendar, h, known_before)
            test = rows[in_fold]
            if train.empty or test.empty:  # the last periods of long horizons have no targets yet
                continue
            ranks = None if rank is None else rank.loc[train.index]
            if names:
                boosters = _fit_horizon(
                    train[feat], alpha.loc[train.index], config, beat=train[target], rank=ranks
                )
                mu = {name: _finite_mean(train[f"f_{name}_{h}"]) for name in names}
            else:
                boosters = _fit_horizon(train[feat], train[target], config, rank=ranks)
                mu = {}
            raw = _predict(boosters, test[feat])
            if names:
                q50_alpha = raw["q50"].to_numpy(dtype=float)
                shift = _factor_shift(test, names, mu)
                for quantile in QUANTILE_NAMES:
                    raw[quantile] = raw[quantile].to_numpy(dtype=float) + shift
                raw["q50_alpha"] = q50_alpha
                raw["alpha"] = alpha.loc[test.index].to_numpy(dtype=float)
                fallbacks += fallback_count(test, h, names)
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
        pred, ranges = calibrate_ranges(pred, data.calendar, h, folds)
        pred["score"] = pred["p_raw"] if ranker else pred["q50"]  # what this model ranks by
        frames.append(pred)
        scored = pred[pred["p"].notna()]
        if not scored.empty:
            metrics[h] = _metrics(scored) | {"range": ranges}
    extra = ["q50_alpha", "alpha"] if names else []
    columns = [
        "day", "symbol", "sector", "dollar_volume_20", *jump, "horizon", "fold", "y", *QUANTILE_NAMES, *RAW_NAMES,
        "p_raw", "p", "score", *extra,
    ]
    predictions = pd.concat(frames, ignore_index=True)[columns] if frames else pd.DataFrame(columns=columns)
    alpha_ic = None
    if names and not predictions.empty:
        comparable = predictions.dropna(subset=["q50_alpha", "alpha"])
        alpha_ic = rank_ic_by_horizon(comparable, "q50_alpha", "alpha") if not comparable.empty else float("nan")
    return WalkForward(predictions, metrics, folds, fallbacks, alpha_ic, ranker)


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
    ranges: dict = field(default_factory=dict)  # horizon → RangeCalibrator of the edges that beat the raw ones
    p_source: str = "beat"  # the booster P is calibrated from: "beat", or "rank" (spec §8)

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
            if h in self.ranges:
                out[list(QUANTILE_NAMES)] = self.ranges[h](out[list(QUANTILE_NAMES)])
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
        # a factor exposure (beta_*) says how the stock moves with a factor, not what moved this
        # forecast; explanations name only the stock's own features
        own = np.array([not f.startswith("beta_") for f in self.features])
        out = {}
        for key, vals in zip(x.index, contrib, strict=True):
            order = [i for i in np.argsort(-np.abs(vals), kind="stable") if own[i]][:top]
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
    boosters, calibrators, ranges = {}, {}, {}
    # the calibrators were fitted on the walk-forward's scores, so the final boosters follow it
    ranker = wf.ranker
    for h in config.horizons:
        oos = wf.predictions[(wf.predictions["horizon"] == h) & (wf.predictions["fold"] > 0)]
        if oos.empty:
            raise ValueError(f"no out-of-sample predictions to calibrate horizon {h} on")
        calibrators[h] = Calibrator.fit(oos["p_raw"].to_numpy(), (oos["y"] > 0).to_numpy())
        adopted = wf.metrics.get(h, {}).get("range", {}).get("adopted") or {}
        edges = [name for name in QUANTILE_NAMES if adopted.get(name)]
        if edges:
            ranges[h] = RangeCalibrator.fit(_as_range(oos, RAW_NAMES).assign(y=oos["y"]), names=edges)
        train = rows[rows[f"y_{h}"].notna()]
        ranks = daily_rank(train, f"y_{h}") if ranker else None
        if names:
            boosters[h] = _fit_horizon(
                train[feat], alpha_target(train, h, names), config, beat=train[f"y_{h}"], rank=ranks
            )
        else:
            boosters[h] = _fit_horizon(train[feat], train[f"y_{h}"], config, rank=ranks)
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
        dict(config.params), config.rounds, names, mu, betas, ranges, "rank" if ranker else "beat",
    )


def _pack(value: str) -> bytes:
    return gzip.compress(value.encode())


def _unpack(blob: bytes) -> str:
    return gzip.decompress(blob).decode()


def to_files(model: FinalModel) -> dict[str, bytes]:
    files = {
        f"h{h}_{part}": _pack(model.boosters[h][part].model_to_string())
        for h in model.horizons for part in (*QUANTILE_NAMES, model.p_source)
    }
    files["screener"] = _pack(model.screener.model_to_string())
    files["calibration"] = _pack(json.dumps({str(h): c.to_json() for h, c in model.calibrators.items()}))
    files["meta"] = _pack(json.dumps({
        "features": model.features, "screener_features": model.screener_features,
        "horizons": list(model.horizons), "params": model.params, "rounds": model.rounds,
        "p_source": model.p_source,
    }))
    if model.ranges:
        files["ranges"] = _pack(json.dumps({str(h): r.to_json() for h, r in model.ranges.items()}))
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
    p_source = meta.get("p_source", "beat")  # a model saved before the ranker has a beat booster

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
        {h: {part: booster(f"h{h}_{part}") for part in (*QUANTILE_NAMES, p_source)} for h in horizons},
        {h: Calibrator.from_json(calibration[str(h)]) for h in horizons},
        booster("screener"), meta["screener_features"], meta["params"], meta["rounds"],
        factor_names, mu, betas,
        # a model saved before range calibration has no `ranges` file and keeps its raw ranges
        {int(h): RangeCalibrator.from_json(d) for h, d in json.loads(_unpack(files["ranges"])).items()}
        if "ranges" in files else {},
        p_source,
    )
