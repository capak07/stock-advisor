# Pipeline

Python 3.12, managed with uv. The repository's `README.md` covers setup, deployment and the manual run.

## Training

`train.yml` runs these every Saturday. To run them by hand, outside market hours, from `pipeline/` with `DATABASE_URL` set:

```bash
scripts/in-docker.sh uv run python -m advisor.training.build --out DIR
scripts/in-docker.sh uv run python -m advisor.model.weekly --data DIR [--market TSX]
```

`advisor.model.weekly` trains, backtests and promotes each market's model (`--market` is repeatable; the default is both). It needs `DATABASE_URL` and the files from `advisor.training.build`.

`DIR/model-report.json` is what it decided, per market: the stored version, whether it was promoted and why, `picks_enabled` and `picks_reason`, the worst horizon's calibration, the mean rank IC and the seconds spent. The job uploads it with `manifest.json` as the `training-report` artifact.

The model's integration test is `tests/integration/test_model_weekly_job.py`. The test image (`scripts/test-image.Dockerfile`) is built the first time `scripts/in-docker.sh` runs.

## Forecasts

Every run's forecasts need an active model, which `train.yml` trains each Saturday; the first Saturday run must come after Plan 3c merges, because its EPS rule changed training too. No model was trained in production before it. Each market's `summary.model` in the run says what it did: `{version, screened, predicted, not_eligible, horizons}` (`predicted` counts stocks; `not_eligible` counts stocks in the forecast set the model may not score, which get `model_eligible: false` in `features_live` and no forecast) (plus `split_events` if the split download failed), `{skipped: "no active model"}`, `{skipped: "no usable horizons"}` or `{failed: ...}`. A failure while forecasting keeps `version` and `screened` next to `failed`, since that model's screener already ranked the shortlist; one at load has only `failed`. Without a model, a market's shortlist ranks by dollar volume and gets no forecasts.

## Picks and verdicts

Stage 8 (`advisor.recommend.stage`) turns each market's forecasts into picks and writes a verdict for every watched symbol, after all earlier stages' writes. Each market's picks are written together or not at all, and a failure degrades the run, never stops its prices publishing.

`summary.picks` has an entry per market:
- `{swing, position}`: how many picks each list got;
- `{disabled: reason}`: the model's backtest gate (`picks_enabled`, `picks_reason`) is off or missing, so no picks, though the watchlist still gets verdicts;
- `{skipped: ...}`: the market had no forecasts (no model, no usable horizons, or the run couldn't publish); `{failed: ...}`: the model or the recommender failed.

`summary.verdicts` exists only when writing the verdicts failed: `{failed: ...}`. A market whose recommender failed gives its watched stocks Hold with "the recommender failed this run".

The picks are in `picks`, the verdicts in `watchlist_verdicts`. A verdict's `details` carries `market_picks_enabled`, `held: true` for a stock that is also held, and a Buy's pick fields (risk level, stop, exit-by date, top factors, catalysts).
