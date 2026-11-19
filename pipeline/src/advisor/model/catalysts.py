"""Drug approval and recall features from openFDA, as wide day x symbol frames.

openFDA refreshes its data about weekly, so a record dated D0 is treated as known `FDA_LAG_DAYS` later
(`known = day + FDA_LAG_DAYS`) and a day reads it only strictly after that, the same in training
(`training.fda_history`) and live (`collectors.openfda`, which looks back `WINDOW_DAYS =
APPROVAL_WINDOW_DAYS + FDA_LAG_DAYS + FEATURE_DAY_MARGIN_DAYS`).

`events` has `symbol`, `kind` ("approval" | "recall"), `day` and `event_id`. An event counts once however
many rows list it (a recall of three products is one event), dated by its earliest row (Ruling R12). A symbol without events reads 0 when
`events` is given, and a source given as None (live: its collector did not run cleanly) reads NaN.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from advisor.collectors.openfda import APPROVAL_WINDOW_DAYS, FDA_LAG_DAYS, RECALL_WINDOW_DAYS
from advisor.model.pit import window_count

CATALYSTS_FEATURES = ["fda_approvals_180d", "fda_recalls_90d"]
_KINDS = (("approval", "fda_approvals_180d", APPROVAL_WINDOW_DAYS), ("recall", "fda_recalls_90d", RECALL_WINDOW_DAYS))


def catalysts_features(events: pd.DataFrame | None, days: pd.DatetimeIndex,
                       symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Wide frames (days x `symbols`) of CATALYSTS_FEATURES.

    `fda_approvals_180d` counts the approvals (originals and new indications) and `fda_recalls_90d` the
    distinct recall events known within APPROVAL_WINDOW_DAYS and RECALL_WINDOW_DAYS before the day.
    """
    symbols = list(symbols)
    if events is None:
        return {name: pd.DataFrame(np.nan, index=days, columns=symbols) for name in CATALYSTS_FEATURES}
    rows = events.assign(day=pd.to_datetime(events["day"]))
    rows = rows.sort_values("day", kind="stable").drop_duplicates(["symbol", "kind", "event_id"]).copy()
    rows["known"] = pd.to_datetime(rows["day"]).astype("datetime64[ns]") + pd.Timedelta(days=FDA_LAG_DAYS)
    return {
        name: window_count(rows[rows["kind"] == kind], days, symbols, window)
        for kind, name, window in _KINDS
    }
