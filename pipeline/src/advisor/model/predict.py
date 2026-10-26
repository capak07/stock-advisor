"""Forecast with the active model: load it, predict its usable horizons, score the screener."""

from dataclasses import dataclass

import pandas as pd
import psycopg

from advisor.model.train import FinalModel, from_files
from advisor.model.weekly import KIND
from advisor.models import Market, PredictionRow
from advisor.store import repo


@dataclass(frozen=True)
class ActiveModel:
    version: str
    model: FinalModel
    usable: tuple[int, ...]


def load_active(conn: psycopg.Connection, market: Market) -> ActiveModel | None:
    """The market's active model, or None when there is none or no horizon of it is honest.

    A model stored before `usable_horizons` existed has none, so it gives no forecasts.
    """
    stored = repo.active_model(conn, KIND[market])
    if stored is None:
        return None
    wanted = {int(h) for h in stored.metrics.get("usable_horizons") or []}
    if not wanted:
        return None
    model = from_files(repo.load_model_files(conn, stored.version))
    usable = tuple(h for h in model.horizons if h in wanted)
    if not usable:
        return None
    return ActiveModel(stored.version, model, usable)


def predict_rows(active: ActiveModel, features: pd.DataFrame, benchmark: str) -> list[PredictionRow]:
    """Forecasts for usable horizons only; a row with a NaN quantile or P(beat) is skipped."""
    out = active.model.predict(features)
    out = out[out["horizon"].isin(active.usable)].dropna(subset=["q10", "q50", "q90", "p_beat"])
    return [
        PredictionRow(
            str(symbol), int(r.horizon), float(r.q10), float(r.q50), float(r.q90), float(r.p_beat),
            benchmark, active.version,
        )
        for symbol, r in zip(out.index, out.itertuples(index=False), strict=True)
    ]


def screen_scores(active: ActiveModel, features: pd.DataFrame) -> pd.Series:
    """The screener's score per symbol, to shortlist stocks for a full prediction."""
    return pd.Series(active.model.screen(features), index=features.index)
