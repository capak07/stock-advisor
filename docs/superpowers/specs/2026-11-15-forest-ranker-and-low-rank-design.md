# Forest Ranker and Low Model Rank: Design

**Date:** 2026-11-15. **Owner request:** "Look for model improvements, different algorithms or patterns", then "Research, test and then build".

## Why

A walk-forward study on the cached US training data (four disjoint quarters of the US stocks, then the full data; scripts in `pipeline/.cache/diag/improve*.py`, outside git) found:

1. **No new pattern helps.** 28 new inputs (chart setups, momentum quality, risk shape, overnight vs daytime returns, seasonality) left the rank IC unchanged or lower.
2. **A random-forest ranking booster helps.** In the quarter samples it raised rank IC from about 0.081 to 0.096–0.110, better in 10–11 of 12 test periods, held on a held-back quarter. On the full data the gain is smaller: +0.001 to +0.014 by horizon, larger at 63 and 126 days, better in 2–4 of 4 periods. It did not help TSX.
3. **The live screener barely ranks.** Its rank IC is 0.02–0.03 against 0.09 for the full model, yet it chooses which 300 of about 3,700 US stocks get a forecast each run. A forest ranker on the same price inputs plus the GARCH volatility ranks at about 0.095 at 21 days and 0.11–0.14 at 63–126 days.
4. **The bottom of a good ranking is reliable; the top is not.** On the full US data the new screener's bottom 10% trailed the average stock by 2.8% over 21 days, 5.9% over 63 and 8.7% over 126, in 4 of 4 (21 days) or 3 of 4 (63, 126) test periods, and 27–57% of those stocks lost 20%+ against the S&P 500 versus 7–29% of all stocks. The top 10% beat the average by under 1%. On TSX the bottom 10% did not trail reliably.

## Goals

- A `forest` model option, judged by the existing benchmark like every other part; nothing changes live unless the benchmark accepts it.
- Replace every model's screener with the forest ranker on price, relative-strength and (for a GARCH model) GARCH-volatility inputs, so the shortlist is chosen by a score that ranks.
- A **Low model rank** flag: US stocks in the bottom 10% of a run's screener scores, shown wherever the owner looks at a US stock.

## Non-goals and anti-goals

- No buy signal from the top of any ranking (the evidence says it does not beat the index).
- No change to Picks, the pick policy, the acceptance rule, calibration or the forecast ranges.
- No TSX or crypto flag. No new pattern features.
- The flag must not be confused with the existing **Avoid** verdict (which is a P(beat) rule on watched stocks): different name, different place in the card.

## Decisions

- **Forest settings** (from the grid; scaled leaf so it holds on any data size): `PARAMS | {"objective": "regression", "boosting": "rf", "num_leaves": 63, "bagging_fraction": 0.6, "bagging_freq": 1, "feature_fraction": 0.3}`, `min_data_in_leaf = max(200, 1% of the training rows)`, 200 rounds. Learns `daily_rank` of the horizon's target, as the ranker does.
- **`ModelConfig.forest: bool`**, `CONFIG_VERSION = 5`; versions 1–4 load with it off. It swaps the ranking booster's settings only, so it needs `ranker` (a forest config without ranker is refused). Name part order: after `ranker`.
- **Benchmark row** `garch+ranker+forest` in every market, before `full+policy`. The benchmark decides; a TSX or crypto rejection is expected.
- **Screener** (all markets, every model trained from now): the forest above on `PRICE_FEATURES + RS_FEATURES` (+ `garch_vol` at the screener horizon for a GARCH model), target `daily_rank` of `y_21` (or the horizon nearest 21). Stored in the same `screener` file; `meta` gains `screener_horizon` and `screener_kind: "forest_rank"`. A model saved before this keeps its binary screener and loads unchanged.
- **Low model rank**: each run, among the US symbols the screener scored, a percentile (0–1, ascending score); `low = pct <= 0.10`. Stored in a new table `screen_ranks (run_id, symbol, pct, low)`, migration `0015`, owner read and pipeline write, as `0013`. Only written for US, only for a run with an active US model whose screener scored at least 100 symbols. A failure is recorded in the run summary and never degrades the run.
- **Where it shows** (web): ticker page header (beside the holding badges, so it shows for a stock without a forecast too), Watchlist row, My Portfolio action cards and hold list, Day trade signal cards (US).
- **Screener garch input** (builder's call): a model has a forecast volatility for its own horizons only, so a garch model's screener reads `garch_vol` at the model horizon nearest 21 sessions (21 for US and TSX). Its target stays `y_21`. Read from the latest published run. Text: badge "Low model rank"; explanation "Bottom 10% of the model's ranking of about N US stocks today. In testing (2021–2026), stocks here trailed the average stock by about 3% over a month and 6% over three months, and more often fell sharply. It is not a sell signal on its own."

## Left to the builder

Component layout of the badge; query shape; test file placement.
