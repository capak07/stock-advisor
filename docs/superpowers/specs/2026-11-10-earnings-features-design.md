# Earnings features — design

**Status:** approved by the owner in chat, 2026-11-10 ("Yes" to step 1 of the model-input plan).

## Why

The stock model's fundamentals are trailing-twelve-month (TTM) ratios only (`model/fundamentals.py`):
a strong latest quarter barely moves a yearly average. Two well-documented effects use the latest
quarter instead: quarter-over-year-ago growth, and post-earnings drift after an earnings surprise. The
weekly training already downloads 8+ years of SEC companyfacts (with 3-month quarterly facts and their
`filed` dates), so these can be built point-in-time with no new data source. This plan adds them as an
optional feature group and lets the existing benchmark decide.

## Goals

- A new optional feature group **`earnings`** (US only, from SEC XBRL facts), point-in-time (a day reads
  only facts filed strictly before it, the same rule as `fundamentals.py`):
  - `rev_growth_q` — latest single quarter's revenue / the same fiscal quarter a year earlier − 1.
  - `op_margin_q_chg` — latest quarter's operating margin minus the year-ago quarter's, in points.
  - `sue` — standardized unexpected earnings: (latest quarter's diluted EPS − the year-ago quarter's) /
    the standard deviation of the previous 8 such year-over-year EPS changes (at least 4 needed), clipped
    to ±5. A self-derived surprise: XBRL has no analyst estimates (`deferred.md:74`).
  - `days_since_report` — calendar days since the latest quarter's facts were filed (drift fades with
    time), capped at 120.
- Single quarters: 3-month facts (80–100 days); a fiscal Q4 is derived as the fiscal year minus the
  9-month year-to-date that ends inside it (as `fundamentals.ttm` does with YTDs); first-reported values,
  best-priority concept (`fundamentals.first_reported`); figures stale after `STALE_DAYS`.
- One new benchmark row, **`ranker+earnings`**, judged by the existing acceptance rule against the
  baseline and the incumbent (`benchmark/accept.py`). Nothing reaches Picks unless it is accepted.
- `ModelConfig` gains `earnings: bool`; config version 4; old versions still load with it off.
- Live forecasts compute the same features from the run's `sec_xbrl` facts (3-year lookback: 12 quarters,
  enough for the year-ago quarter and 8 prior changes on most companies).

## Non-goals

- Analyst estimates, earnings dates, 8-K or insider inputs (step 2, separate plan).
- TSX (no SEC data): the group is NaN there; TSX and crypto get no `earnings` row.
- Any change to the baseline, the accepted config, Picks or the acceptance rule.

## Acceptance

The benchmark decides. Expect a possible rejection: the US ranker's worst calibration is 5.1 points with
a 5.0 limit (5.5 for the incumbent), and earlier additions failed on pinball by 0.6%. A rejection is a
valid result; the report says why.

## Owner step after merge

Run the benchmark workflow (`benchmark.yml`, manual) once; the report shows the new row.
