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

### Group history

`history.yml` runs every Saturday at 02:00 UTC (and by hand) and downloads the US data groups' history into an actions cache: FINRA short interest and volume, Yahoo analyst events and earnings, SEC material events, 13D/G, insider trades, 13F holders and openFDA events. `train.yml` and `benchmark.yml` only restore that cache and never download group history; a group whose cache is missing or older than 21 days is unavailable for that run. The workflow uploads its `manifest.json` as the `history-report` artifact.

`advisor.training.build` takes these options for the groups:

- `--groups all|none|accepted|a,b,c`: which groups' history to build (default `all`; a comma list such as `short,holders` picks some). `train.yml` uses `--groups accepted`, which reads the accepted US config from the database, so it cannot be combined with `--no-db`;
- `--history-cache DIR`: the group-history cache (default `<out>/history-cache`);
- `--history-only`: download only the group history into the cache (what `history.yml` runs; needs `--history-cache`). It exits 1 when a wanted group ends unavailable, after writing `manifest.json`;
- `--no-history-download`: copy the fresh groups from the cache and download nothing (what `train.yml` and `benchmark.yml` run; needs `--history-cache`).

The files, written to `--out` next to the price files: `short_interest.parquet`, `short_volume.parquet`, `analyst_events.parquet`, `insider_trades.parquet`, `material_events.parquet`, `large_holders.parquet`, `holders.parquet`, `earnings_estimates.parquet` and `fda_events.parquet`. A group that failed or was empty is listed under `unavailable` or `empty` in `manifest.json`, and its model rows fail closed.

The model's integration test is `tests/integration/test_model_weekly_job.py`. The test image (`scripts/test-image.Dockerfile`) is built the first time `scripts/in-docker.sh` runs.

## Forecasts

Every run's forecasts need an active model, which `train.yml` trains each Saturday; the first Saturday run must come after Plan 3c merges, because its EPS rule changed training too. No model was trained in production before it. Each market's `summary.model` in the run says what it did: `{version, screened, predicted, not_eligible, horizons}` (`predicted` counts stocks; `not_eligible` counts stocks in the forecast set the model may not score, which get `model_eligible: false` in `features_live` and no forecast) (plus `split_events` if the split download failed), `{skipped: "no active model"}`, `{skipped: "no usable horizons"}` or `{failed: ...}`. A failure while forecasting keeps `version` and `screened` next to `failed`, since that model's screener already ranked the shortlist; one at load has only `failed`. Without a model, a market's shortlist ranks by dollar volume and gets no forecasts.

## Picks and verdicts

Stage 8 (`advisor.recommend.stage`) turns each market's forecasts into picks and writes a verdict for every watched symbol, after all earlier stages' writes. Each market's picks are written together or not at all, and a failure degrades the run, never stops its prices publishing.

`summary.picks` has an entry per market:
- `{swing, position}`: how many picks each list got;
- `{disabled: reason}`: the model's backtest gate (`picks_enabled`, `picks_reason`) is off or missing, so no picks, though the watchlist still gets verdicts;
- `{skipped: ...}`: the market had no forecasts (no model, no usable horizons, the model failed, or the run couldn't publish); `{failed: ...}`: a step of the picks stage failed (the feature day, the inputs, the news read, the recommender, the contributions or the write).

`summary.verdicts` exists only when writing the verdicts failed: `{failed: ...}`. A market whose recommender failed gives its watched stocks Hold with "the recommender failed this run".

The picks are in `picks`, the verdicts in `watchlist_verdicts`. Each stock verdict's `details` carries `market_picks_enabled` (a coin's doesn't), `held: true` for a stock that is also held, and a Buy's pick fields (risk level, stop, exit-by date, top factors, catalysts).
