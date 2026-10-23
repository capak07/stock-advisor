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
