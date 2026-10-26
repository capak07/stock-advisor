from datetime import UTC, datetime

import pytest

from advisor.model.dataset import load_market
from advisor.model.predict import load_active, predict_rows, screen_scores
from advisor.model.train import PARAMS, TrainConfig, fit_final, to_files, walk_forward
from advisor.models import Market
from advisor.store import repo
from model_data import write_market

FAST = TrainConfig(horizons=(5, 63), rounds=40, params={**PARAMS, "min_data_in_leaf": 50, "num_threads": 2})


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("tsx")
    write_market(out, Market.TSX, stocks=20, days=1100)
    data = load_market(out, Market.TSX)
    return data, fit_final(data, walk_forward(data, FAST), FAST)


def store(db, model, usable):
    at = datetime(2026, 10, 24, 10, tzinfo=UTC)
    repo.save_model(db, "stock_tsx-1", "stock_tsx", at, {"usable_horizons": usable}, 3.0, to_files(model))
    repo.activate_model(db, "stock_tsx", "stock_tsx-1")


def test_only_usable_horizons_are_predicted(db, trained):
    data, model = trained
    store(db, model, [63])
    active = load_active(db, Market.TSX)
    x = data.rows.drop_duplicates("symbol").set_index("symbol")[data.features]
    rows = predict_rows(active, x, "XIU.TO")
    assert {r.horizon_days for r in rows} == {63}
    assert all(r.q10 <= r.q50 <= r.q90 and 0 <= r.p_beat <= 1 and r.model_version == "stock_tsx-1" for r in rows)
    run_id = db.execute("insert into runs (kind, et_date) values ('pre_open', '2026-10-26') returning id").fetchone()["id"]
    repo.write_predictions(db, run_id, rows)
    assert db.execute("select count(*) as n from predictions where run_id = %s", (run_id,)).fetchone()["n"] == len(x)


def test_a_model_without_usable_horizons_gives_no_forecasts(db, trained):
    _, model = trained
    store(db, model, [])
    assert load_active(db, Market.TSX) is None
    assert load_active(db, Market.US) is None  # no model at all


def test_the_screener_scores_every_stock(db, trained):
    data, model = trained
    store(db, model, [5, 63])
    x = data.rows.drop_duplicates("symbol").set_index("symbol")[data.features]
    scores = screen_scores(load_active(db, Market.TSX), x)
    assert list(scores.index) == list(x.index) and scores.between(0, 1).all()
