# Exit plan for holdings — design

**Status:** approved by the owner 2026-11-20 ("Go with the best approach", then "Yes" to this design, in the owner's other session). Calls Claude made are marked *(call)*.

## Why

My Portfolio shows an "Exit by" date for each holding. The owner's complaint: a date alone is not
helpful. It says nothing about how far the stock may rise, what price to sell at, or whether selling on
that date means selling at a loss.

What the date is today:

- It is the day the forecast window ends: the latest price day plus the forecast horizon
  (`portfolio/stage.py`, `action_rows`). For a holding not linked to an open pick it is recomputed on
  every run, so it moves forward each day and is never reached.
- The forecast behind it is a range of return **relative to the benchmark** (SPY, XIU.TO, BTC), not a
  price. Nothing turns it into dollars.
- The owner's cost plays no part, except in the "up 25% and fading" trim rule and the tax warnings.

What the research found (sources at the end):

- Single price targets are unreliable even from professionals: 38% of analyst 12-month targets were met
  at the end of the period, 64% were touched at some point, and the average error was 45%. Our model is
  weaker than that. One "sell at $X" number would overstate what it knows; a range with chances is
  honest.
- Touching a price before a date is much likelier than closing above it on the date (about twice, for a
  price with no drift). So a limit sell at a target price is a usable tool.
- "Never sell at a loss" costs money as a rule: the winners investors sold went on to beat the losers
  they kept. What the owner paid doesn't change where the stock goes next.
- The standard exit framework has three exits, whichever comes first: a profit target, a stop and a
  time limit. The app has the stop and the time limit. The profit target is missing.

## Goals

1. **Each holding shows an exit plan** in place of the bare date:
   - the **expected price range** on the re-check date: low, middle and high, in the asset's own
     currency, with the middle's gain or loss against today's price;
   - a **sell-at price**: a level with about a 1-in-3 chance of being touched before the re-check date,
     with the gain it would lock in against the owner's cost;
   - a **break-even line** when the holding is under water: the price at which the owner gets their
     money back and the chance the price touches it before the re-check date;
   - the chance the **stop is hit before the sell-at price**;
   - the date, renamed **"Re-check by"**.
2. **Every holding with a price history gets a plan**, including coins and stocks the model has no
   forecast for. Those plans come from the asset's own volatility and are labelled "from volatility
   only — no view on direction".
3. **The chances are checked against history before they are shown as validated**, and again live by
   the grader. A plan part that fails its check is not shown.
4. **Reaching the sell-at price shows up in "What's new on your stocks"** through the existing price
   alerts.

## Non-goals

- Changing the Sell / Trim / Add / Hold rules. The plan informs; `decide` is untouched.
- A plan for picks, the watchlist or the Invest page. Holdings first; picks can follow once the plan
  has graded history.
- Intraday paths. Paths step in daily closes, as stops and grading do.
- Placing orders. There is no broker connection.
- A new trained model for touch chances (approach C below), unless the backtest fails.

## Anti-goals

- A single target price presented as a prediction.
- Telling the owner to wait for break-even. When the chance of getting back to cost is low, the card
  says so.
- A touch chance shown for a plan class whose backtest missed its tolerance.
- A directional-looking range for an asset with no forecast.

## Approaches

- **A. Formula from the model's range.** Fit a normal curve to q10/q50/q90 and read touch chances from
  the reflection formula. Cheap, but real stocks jump and gap more than the formula assumes, most of
  all the small caps and coins the owner holds, so the chances would run confident.
- **B. Simulated price paths.** Replay possible paths built from the asset's own past daily moves,
  scaled to the model's range, and count how many touch each level. One method gives every number,
  keeps the asset's jumpiness, and works without a forecast. **Chosen** by the owner ("go with the best
  approach", 2026-11-20) on Claude's recommendation.
- **C. A trained model on "target hit, stop hit or time ran out"** (triple-barrier labels). Likely the
  most accurate, but a full training-and-acceptance project and nothing for assets outside the model.
  Kept as the fallback if B's backtest fails.

## Design

### 1. The plan's inputs, per holding

- the asset's daily closes: bars for stocks, Coinbase candles for coins, oldest first, flagged days
  dropped (as `_stop` does);
- today's price (`_Priced.price`) and feature day;
- the action's forecast row (`Action.horizon`, q10, q50, q90), when there is one;
- the trailing stop (`Holding.trailing_stop`);
- the position's cost and value in CAD.

**Horizon** *(call)*: the action's horizon when it has a forecast; otherwise 21 sessions for a stock
and 21 calendar days for a coin. The re-check date is the feature day plus the horizon on the asset's
calendar, as `exit_by` is computed today. A holding linked to an open pick keeps the pick's `exit_by`
as its re-check date when that is later, as today.

**Break-even price** *(call)*: `price × cost_cad / value_cad`: the native price at which the position's
CAD value equals its cost at today's exchange rate. Shown only when value is under cost.

### 2. Turning the forecast into a price range

The model's quantiles are excess returns over the benchmark (`forward_excess`: the stock's simple
forward return minus the benchmark's). An absolute price needs the benchmark's own move added back:
both its typical drift and its spread. Adding the drift alone would make the range too narrow, most of
all for coins measured against BTC. So the paths of §3 carry the benchmark's moves too, and the range
is read off the combined paths *(call)*.

`d` is the benchmark's median return over the same horizon across its stored history (all overlapping
windows). The plan stores `d` and the page states it ("assumes SPY drifts +0.9% over 21 days").

For a coin with a forecast (excess over BTC), the benchmark is BTC the same way. An asset with no
forecast has no q's and no `d`.

The builder must confirm what the active model's quantiles are measured against before relying on
this: if a factor-adjusted target is ever the active config (Plan 6c), the add-back is the factor
exposure times the factor drift, not the benchmark alone, and the plan must refuse to convert until
that is implemented.

### 3. Simulated paths

New module `advisor/portfolio/exit_plan.py`, pure functions, no I/O.

- **Source moves:** the asset's daily log returns over the last 252 closes (minimum 60 *(call)*; fewer
  means no plan, with the reason "too little price history").
- **Paths:** 4,000 paths *(call)* of `horizon` steps by a block bootstrap, blocks of 5 days *(call)*,
  so volatility clustering and gaps survive. The random seed is derived from the symbol and the feature
  day, so a re-run of the same day gives the same plan.
- **With a forecast:** each sampled day carries the pair (asset move, benchmark move) from the same
  date, so their co-movement survives. All arithmetic is in log space; a quantile `q` becomes
  `log(1 + q)`.
  - The **excess** part (asset log move minus benchmark log move) is rescaled: every daily value is
    multiplied by one scale so the 10–90 width of the summed ends equals
    `log(1 + q90) − log(1 + q10)`, then a constant daily drift is added so the median end equals
    `log(1 + q50)`.
  - The **benchmark** part has its sample mean removed and a constant daily drift added so its median
    end equals `log(1 + d)`.
  - The asset's path is the sum of the two. Treating a simple-return excess as a log-return difference
    is an approximation; §6's coverage check measures whether it holds.
- **Without a forecast:** no rescaling; the sample mean is removed so the median path is flat. This is
  the "volatility only" plan.
- **Stop:** the current trailing stop, held fixed along the path *(call)*. In life it rises as the
  price rises; fixing it slightly overstates the chance of reaching the sell-at price before the stop.
  The page doesn't claim otherwise and the backtest measures the real thing.

### 4. What is read off the paths

| Field | Meaning |
|---|---|
| `low`, `mid`, `high` | the 10th, 50th and 90th percentile of the end prices |
| `sell_at` | the price that one third of the paths close at or above on some day (`TOUCH = 1/3` *(call)*) |
| `p_touch` | the share of paths that touch `sell_at`: 1/3 by construction, replaced by the calibrated value once the backtest has one |
| `p_stop_first` | the share of paths that close at or under the stop before touching `sell_at`; null without a stop |
| `p_up` | the share of paths ending above today's price |
| `breakeven`, `p_breakeven` | the break-even price and the share of paths that touch it; null when the holding isn't under water |
| `drift`, `basis` | `d` from §2, and `"forecast"` or `"volatility"` |
| `horizon`, `recheck_by` | as §1 |

`sell_at` is not shown when it is at or under today's price plus the round-trip cost, or when it is at
or under the stop.

Touches are counted on daily closes. A limit order fills intraday, so the real touch chance is a little
higher; the backtest measures both and the page says "closes at or above".

### 5. Storage

Migration `0016_exit_plan.sql`:

- `holding_actions.exit_plan jsonb` (nullable): the table of §4. `exit_by` stays and keeps its value,
  so old rows, the grader and the pick link are untouched.
- `holding_action_outcomes`: `touched_sell_at boolean`, `touched_breakeven boolean`, `max_close numeric`
  (all nullable), filled by the grader when the horizon ends.

`HoldingActionRow` gains `exit_plan: dict | None`. `action_rows` builds it after `decide`. A failure to
build one holding's plan leaves that holding's plan null with a reason in the run summary; it never
fails the stage.

### 6. Checking the chances (acceptance)

A new benchmark variant in the evaluation harness (`advisor/benchmark`), run with `benchmark.yml`:

- **Sample:** walk-forward folds as the harness already cuts them; for each fold, sampled
  (stock, day) pairs with a usable forecast, plus the same pairs with the forecast masked (the
  volatility-only class), plus coins on their candle history. Nothing dated after the sample day is
  read to build a plan.
- **Calibration, per class (forecast / volatility-only / coin):**
  - sell-at touch rate against the stated 1/3: within ±5 points overall and ±8 in each volatility
    third;
  - range coverage: the share of end prices between `low` and `high` against 80%, within ±5 points;
  - break-even and stop-first chances in five bins: stated against realised, worst bin within ±10
    points.
- **Value of the sell-at order:** "limit sell at `sell_at`, else stop, else sell on the re-check date"
  against "stop, else sell on the re-check date", net of round-trip costs, over the same pairs. The
  sell-at price is shown only for a class where the first is not worse (mean difference ≥ 0 at the
  harness's usual confidence). Otherwise that class shows the range and chances without a sell-at
  price, and the page says why.
- **Result:** stored with the benchmark report per class: `pass`, `range_only` or `fail`, with the
  measured rates. The live stage reads the latest result and (a) hides what failed, (b) replaces
  `p_touch` with the measured touch rate for the holding's class. Until a benchmark has run, plans show
  under a "Not validated yet" note, as the Invest page does for unvalidated picks.

The tolerances are Claude's *(call)*; they mirror the 5-point calibration rule the model's horizons
already pass.

**Live check:** the grader records `touched_sell_at`, `touched_breakeven` and `max_close` for each
graded holding action. Track Record (when built) shows stated against realised.

### 7. What the owner sees

Holdings table: the "Exit by" column becomes "Exit plan".

```
Symbol   …  Trailing stop   Exit plan                                         Risk
ABCD        US$4.10         Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)      High
                            Sell at US$5.60 · about 1 in 3 · +18% on cost
                            Stop first: 22%
WXYZ        US$1.02         Range by Dec 19: US$0.95 – 1.20 – 1.55 (0%)       Very High
                            Break-even US$1.90 · reached in 6% of cases
                            From volatility only — no view on direction
```

- The Hold list line becomes "hold ~21 days · range US$4.20–6.10 · sell at US$5.60 · re-check Dec 19".
- Action cards (Sell, Trim, Add, Review) show the range line and, for a holding under water, the
  break-even line.
- When `p_breakeven` is under 25% *(call)*, the break-even line reads "Unlikely to get back to your cost
  by {date}: reached in {p}% of cases. Your cost doesn't change where it goes next." in the warning
  style.
- The ticker page's forecast card gains the same plan for a held asset.
- Currency is the asset's own, as stops are (`stopCurrency`).

**"How to place it"** (`web/lib/orders.ts`): a sell-at line, "Limit sell {qty} sh at {sell_at}, expiry
90 days", only for whole shares (Wealthsimple fills fractions as market orders only). **To verify
before building:** whether Wealthsimple accepts a limit sell and a stop-limit sell on the same shares
at once (shares already owned can't carry a bracket). If it doesn't, the line is not shown for a
holding with a stop; the price alert below does the job instead and the stop stays in place. The stop
always wins that conflict.

**Price alert:** the plan offers "Alert me at {sell_at}" using the holding monitor's price alerts
(`0012`). *(call)* It is offered, not created automatically, so the owner's alert list stays theirs.

### 8. Wording rules

- Never "target price" or "will reach". Use "range", "sell at", "about 1 in 3", "reached in N% of
  cases".
- Every plan names its basis: "from the model's forecast" or "from volatility only".
- The benchmark drift assumption is shown once per plan with a forecast.
- Docs: spec §7.3 and §9 (My Portfolio) updated; "exit-by" on holdings becomes "re-check by". Picks
  keep "exit by".

## Rulings from the builder check *(all calls)*

- **Prices for the backtest:** the harness's `DailyPanel.close` already holds sessions × symbols closes;
  a plan at a sample day reads only rows up to that day.
- **Backtest stop:** a sampled (stock, day) pair is treated as bought that day: its stop starts at
  `price − trail_atr × ATR` and, in the value test, trails upward on closes as `trailing_stop` does. The
  stop-first calibration compares the plan's fixed-stop chance against that trailing reality. Live, the
  simulation's stop is exactly `Holding.trailing_stop`.
- **Volatility thirds:** terciles of `atr_14_pct` among the fold's sampled pairs.
- **Coins:** the volatility-only coin class is judged on the coin harness's universe; a held coin
  outside it uses that class's result. A coin's range, sell-at and break-even are in USD, as its
  trailing stop is; its order line and alert follow whatever the coin's stop line already does in
  `orders.ts` for currency.
- **Re-check date without a market calendar:** plain calendar-day arithmetic for coins. The date lives
  in `exit_plan.recheck_by`; the `exit_by` column keeps today's behaviour (null for coins and for
  holdings without a horizon).
- **Which result a plan may use:** a benchmark result is keyed by class and by a plan-code version
  constant; the forecast classes are also keyed by the model config version. No matching result means
  "Not validated yet". The first result exists after the owner dispatches `benchmark.yml` once after
  the merge; showing unvalidated plans under that note until then is intended, as on Invest.
- **Live calibration:** touches are counted on closes after the feature day up to the horizon's end.
  A holding sold or exited before then is left out of the stated-against-realised figures.
- **Alert:** "Alert me at {sell_at}" opens the existing alert form prefilled (direction above, the
  plan's price, note "exit plan sell-at"); the owner saves it, so the insert stays the owner's.
- **Limit sell beside a stop:** hidden by default for a holding with a stop, until the Wealthsimple
  check says both orders can stand on the same shares.
- **2026-11-20, controller rulings R5 and R3** *(calls)*: the re-check date is the feature day plus the plan's own horizon, also for a holding linked to an open pick (the pick's later exit-by stays only in `exit_by`), replacing §1's last sentence on the horizon; coin plans are volatility-only for now, and §2's coin-with-forecast path is deferred.
- **2026-11-20, controller ruling R12** *(call)*: the simulated stop trails along each path as `trailing_stop` moves it (today's ATR fraction held fixed; the highest close starts at today's price), replacing §3's "held fixed" and the fixed-stop note above. Reason: the benchmark check walks a trailing stop, and against it the fixed-stop chance was 24 points off on driftless random walks (9.6 after the change, inside the 10-point tolerance). Without an ATR or a trail multiple the stop stays fixed.

## Constraints

- The stage must stay inside the run's time budget: 4,000 × ≤126 steps per holding is vectorised numpy,
  a few milliseconds each. The owner holds a handful of positions.
- Point-in-time: the benchmark variant reads nothing dated on or after the sample day's next session.
- Full-US walk-forward runs out of memory in Docker; the variant samples pairs and must run within
  `benchmark.yml`'s limits (the "80% rule" on timings applies).
- `web/` uses a Next.js with breaking changes: read `node_modules/next/dist/docs/` before writing page
  code.

## Left to the builder

- The exact bootstrap implementation and the quantile-matching arithmetic, with unit tests for: seed
  stability, the ends matching q10/q50/q90 within sampling error, a flat median without a forecast, and
  monotonic touch chance in the level.
- How many (stock, day) pairs the variant samples, chosen from measured timings.
- Where the latest benchmark result per class is read from at run time (the stored benchmark report is
  the intended source).
- The Wealthsimple check in §7, recorded in the order-guidance design's Sources.

## Sources

- Bradshaw, Brown & Huang (2013), "Do sell-side analysts exhibit differential target price forecasting
  ability?", Review of Accounting Studies 18(4). The 38% / 64% figures are from a copy of the abstract.
- Odean (1998), "Are investors reluctant to realize their losses?", Journal of Finance.
- Kaminski & Lo (2014), "When do stop-loss rules stop losses?", Journal of Financial Markets.
- Han, Zhou & Zhu, "Taming momentum crashes: a simple stop-loss strategy" (results before costs).
- López de Prado (2018), Advances in Financial Machine Learning, ch. 3 (the triple-barrier method).
- The reflection principle for Brownian motion (touch chance ≈ twice the chance of ending beyond).
