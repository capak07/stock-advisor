# Runners: swing trades on cheap stocks that start to run — design

**Status:** draft for the owner's approval, 2026-11-24 (builder check done; the owner chose a frozen rule).

## Why

On 2026-11-24 the owner watched AKAN (Akanda Corp.) up about 400% in a month and JAGX (Jaguar Health) about
60% in a week, and asked why the app caught neither. The Picks model can't see them by design: it scores only
stocks at US$1 or more, trading US$1M a day or more, with 60 sessions of history (main spec §4.3), and its
300-stock shortlist leans to stocks over $5 (on 2026-11-23, 14 of 401 forecasts were $1–5, none under $1).
A month before its run AKAN was $0.67–0.81 and traded about $60–130K a day.

The owner wants a separate list for stocks under $5 that catches moves like these, **kept apart from Picks,
Invest and the holdings advice**, and traded as **swing trades** (a few days to about two weeks), not intraday.

## The approach the owner picked (2026-11-24)

Three ways were considered:

- **A. Predict the run before it starts:** a model that forecasts which cheap stocks will rise 50% or more
  within a month. Catches the start of a move, but these runs usually begin with news, a split, an offering
  or social media that daily prices don't foreshadow (AKAN drifted down until 2026-11-13, then traded 89M
  shares against about 80K normally and doubled in a day). Expect weak results and many false alarms.
- **B. Ride the run once it starts (picked):** flag a stock on its first huge-volume up day ("ignition"),
  enter at the next open, and hold days to two weeks with a stop and a target. Gives up the first jump, avoids
  the false alarms, and can be tested honestly on history. It would have flagged AKAN on 2026-11-13 at about
  $1.36, with most of the month's move ahead.
- **C. Lower the Picks filters to include cheap stocks:** rejected. It mixes these stocks into Picks, which
  the owner ruled out, and the Picks model (21–63 day forecasts against SPY) isn't built for one-week bursts.

A may be tried later as a measured experiment; it is not part of this build.

## Goals

1. Every trading day, before the open, list the US stocks priced $0.50–$5 that had an ignition day
   yesterday, each with a plan: entry at the open, stop, target, hold-by date and shares for the owner's max
   loss.
2. Flag the traps that sink cheap stocks on each signal: a pending share sale, a recent reverse split, an
   exchange deficiency notice.
3. Test the rule honestly on history before the page calls anything worth taking, and keep a live paper
   record of every signal after costs.
4. Keep it entirely separate: its own page, tables and track record.

## Non-goals

- Changing Picks, Invest, the forecasts, the stock model or the holdings advice. Runners never appear there,
  and a held runner gets no exit plan from the model.
- Intraday signals (the Day trade page covers those), orders, broker connections, notifications.
- TSX and TSX Venture stocks (US only to start: the owner trades US stocks in the non-registered USD account).
- Stocks under $0.50, OTC/pink sheets, warrants, rights, units, preferreds and funds.
- Predicting a run before it starts (approach A).

## Anti-goals (it fails even if it works technically when…)

- It reads as a recommendation before its record earns that: every signal is labelled paper until the gate
  below is passed.
- A backtest that only looks good because the stocks that went bust are missing from the data is presented
  as evidence (see "Known bias").
- It hides the cost of trading cheap stocks: the record is always after an estimated spread.

## The rule

All numbers below are starting values. The backtest (below) may choose among the listed alternatives only,
on the older part of history, and must confirm the choice on the newest part it never saw.

### Universe (each trading day)

US common stocks and ADRs from the run's existing Nasdaq symbol directory, excluding funds, warrants, rights,
units and preferreds (the directory's flags and suffixes), with a signal-day close of **$0.50 to $5.00**.

### Ignition day (day D, read from complete daily bars)

All of:

- **Volume** on D at least **10×** the average daily volume of the 50 sessions before D (alternatives 5×, 20×).
- **Close** on D at least **20%** above the previous close (alternatives 15%, 30%).
- **Close in the upper half:** close in the top **50%** of D's high–low range (alternatives top 25%, none).
  AKAN's ignition (2026-11-13: low $0.726, high $1.70, close $1.36) closed at 65% of its range, so a top-25%
  rule would have missed it.
- **Dollar volume** on D (close × volume) at least **US$2M**, so the stock can actually be traded.
- **First ignition in 20 sessions:** a stock that already ignited in the 20 sessions before D doesn't signal
  again (a running stock gives one signal, not one a day).
- At least **50 sessions** of history before D (for the volume average). A stock with a reverse split in that
  window uses split-adjusted bars (below); if the adjustment can't be confirmed, it is skipped and counted.

### Plan for a signal

- **Entry:** day D+1's open. The page shows the signal before the open, with "enter at the open"; the record
  uses the actual D+1 open.
- **Gap rule:** none by default (alternatives: skip when D+1 opens more than 15% or 25% above D's close;
  a skip is recorded as **skipped: gapped up** and counted separately). AKAN opened 41% above its ignition
  close on the next session (2026-11-16, $1.92), so a 15% rule would have skipped it.
- **Stop:** the **higher** of D's low and **25% under the entry**, rounded down to the cent, so a huge
  ignition day doesn't give a stop far below the entry (alternatives: D's low alone; 35% under the entry).
  R = entry − stop. Before the open the card shows the plan from D's close as the entry; the record and the
  open-runners list use the actual open.
- **Target:** entry + **2R** (alternatives 1.5R, 3R).
- **Hold by:** **10 sessions**, the entry day counting as day 1 (alternatives 5, 20); sold at that day's
  close if neither stop nor target was hit. The entry day's own bar (after the open) can hit the stop or the
  target. *(Designer's call, from the builder check.)*
- **Daily bars decide outcomes:** a day whose low reaches the stop is a stop at the stop price (or at the open
  if it opened below it); a day whose high reaches the target is a target at the target price (or the open if
  it opened above). A day that touches both counts as **the stop** (conservative).
- Long only.

### Cost

Cheap stocks pay wide spreads, and that is most of the cost. No currency conversion (the owner's USD account).

- **Spread estimate per signal:** the Corwin–Schultz estimate from D's and D−1's high and low, with a floor of
  **1.0%** round trip and a cap of **10%**. *(Builder's call within this: the estimator or a documented
  equivalent from daily bars.)*
- **Cost in R** = cost % × entry ÷ (entry − stop) ÷ 100. **Net R** = gross R − cost in R.

## The honest test (before the page may call anything worth taking)

- **Data:** the weekly training build's 8 years of daily bars for the US universe (`train.yml` /
  `history.yml` already download them), with ignition days found exactly as live.
- **Choose, then confirm:** pick the rule's alternatives on the oldest two thirds of the history (by the
  average net R, with at least 200 signals), then report that one rule, unchanged, on the newest third.
  *(Designer's calls, from the builder check:)* the search moves **one setting at a time** from the starting
  values (about 15 variants in all, not a joint grid, to limit overfitting), and the report says how many
  variants were tried. Gap-skipped signals are not trades and don't count toward the 200 or the 100. If no
  variant reaches 200 signals, the starting values stand and the report says "too few signals to choose".
- **Prices as traded:** the price band ($0.50–$5) and the $2M dollar-volume test use prices **as they traded
  on the day**, rebuilt from the training build's adjusted bars and its split events; returns inside a trade
  use adjusted bars. Without this, a stock that later reverse-split looks expensive and thin in its old bars
  and the band misfires. *(Designer's call.)*
- **Report** (stored and shown on the page): signals, skipped for gaps, target / stop / held-to-date counts,
  average and median net R, the share of trades that lost more than 1R (gaps through the stop), and the worst
  10 trades, for both parts.
- **Known bias:** the symbol directory lists today's stocks only, so cheap stocks that were delisted or went
  bust are missing. Many penny stocks end that way, so the backtest is optimistic. The page says so next to the
  numbers.

## One frozen rule (owner's decision, 2026-11-24)

- The **first** backtest chooses the rule once (choose, then confirm, as above). That rule is **frozen** as
  rule version 1 and stored with its settings; the live list uses it and every signal row records its rule
  version.
- Later weekly backtests **report** the frozen rule on fresh history, and what the search would pick now,
  side by side. They never change the live rule. Switching to a new version is the owner's decision (a
  settings action or a one-line config change, builder's call), and the live record and the gate restart
  for the new version; old signals keep their version.
- Until the first backtest has run, the live list uses the starting values as version 0, labelled so.

## Paper mode and the gate

Every signal is labelled **"Paper: testing"** until **both** hold:

1. The newest-third backtest shows an average net R above 0 over at least 100 signals, and
2. The live record **of the current rule version** has at least **40 closed signals over at least 2 months**
   with an average net R above 0.

Before that the page still shows every signal and its plan, so the owner can watch, but says plainly that the
rule hasn't shown an edge. If the gate later fails on the rolling record, the label comes back.

## Warnings on each signal (from SEC filings, US only)

For each signal stock (a handful a day), read its SEC filing list once:

- **Share sale pending or just priced:** an F-1, S-1, F-3, S-3 (or an amendment) in the last 90 days, or a
  424B prospectus in the last 30 days. "Akanda filed an F-1/A on Nov 20: a share sale may be pending."
- **Recent reverse split:** a split ratio below 1 in Yahoo's split events, or an 8-K item 5.03 / 6-K that
  mentions a reverse split, in the last 90 days.
- **Exchange deficiency notice:** an 8-K item 3.01 in the last 12 months.

Warnings show on the card; they don't block the signal. The record keeps them, so later it can show whether
signals with a pending share sale did worse.

## The page (`/runners`, "Runners", under More on the phone; after Day trade in the sidebar)

(AKAN's real 2026-11-13 bar; the spread, the share count at 1.40 USD/CAD and the warning's timing are
illustrative. On the real open, $1.92, the stop would be $1.44, the target $2.88, reached on 2026-11-18 (high $4.67; the stop was never touched; that day closed at
$4.03): +2R before costs.)

```
Runners · under $5 · swing trades                          Paper: testing
Signals from Friday's close, for today's open (Mon, Nov 16)

┌ AKAN  Akanda Corp.                             ⚠ share sale pending ┐
│ Ignition Fri: +102% on 89M shares (77× normal), closed at 65% of    │
│ the day's range                                                      │
│ Enter at the open · if it opens near $1.36: stop $1.02 (25% under), │
│ target $2.04 (2R) · hold by Nov 30 · ≈ 105 shares for C$50 max loss │
│ Est. spread 2.0% = 0.08R                                             │
└──────────────────────────────────────────────────────────────────────┘
Open runners: … (each with its R so far and day n of 10)

Track record (live, after costs) · 20 and 60 sessions
Backtest · newest third, unseen when chosen · optimistic: dead stocks missing
```

- **Today's signals** as cards (above), newest first; "No ignition yesterday." when none.
- **Open runners:** every signal still inside its hold, with its R so far, as of the last run.
- **Track record:** live closed signals over the last 20 and 60 sessions (count, target / stop / held-to-date
  / skipped, average and median net R, sum), labelled "paper".
- **Backtest card:** the report above, with the bias note.
- **Standing notes:** not financial advice; nothing is ordered; cheap stocks gap, halt and get diluted, and a
  stop can fill far below its price; frequent short trades in a TFSA can be treated as business income, so the
  non-registered account is the natural home (not tax advice).
- **Settings:** "Runners max loss per trade (C$)", default 50; shares = floor(max loss at the latest USD/CAD ÷
  R). The card says when one share already risks more than the max loss.

## How it runs

- **In the existing pre-open run** (about 8:15 AM ET, `run.yml`): the run already downloads daily bars for
  the whole US universe. A new stage finds yesterday's ignitions in those bars, builds their plans, reads
  their filings and stores them. It never fails the run: a runners failure is recorded in the run summary and
  the page says the morning's check failed.
- **Tracking:** the pre-open run also closes out open runners from the previous day's complete bar (stop,
  target or hold-by). The entry price is filled from D+1's open by the next run after it.
- **The backtest** runs in the weekly training job after the history build, and stores its report.
- **Code:** a new `pipeline/src/advisor/runners/` package (rule, plan, cost, warnings, tracking, backtest), SQL
  in `store/repo.py`, the page under `web/app/(app)/runners/`.

## Data

Migration `0018_runners.sql`, with the usual RLS (owner reads, pipeline writes) and grants:

| table | holds |
| --- | --- |
| `runner_signals` | one row per (signal day, symbol): rule version, ignition stats (change %, volume ×, dollar volume, close position), stop, target, hold-by date, spread estimate, cost in R, warnings (jsonb), status (waiting / open / skipped / target / stop / held), entry and exit day and price, gross and net R |
| `runner_backtests` | one row per weekly backtest: the frozen rule's report on fresh history, what the search would pick now, both parts' reports (jsonb), variants tried, the data's date range, signals skipped as split-suspect |
| `runner_rules` | one row per rule version: its settings (jsonb), when it was chosen, from which backtest, and whether it is the live one |

Settings gains `runners_max_loss_cad` (default 50). Signals are kept 2 years.

## Constraints

- Free, keyless data only (Yahoo daily bars, SEC EDGAR with the existing user agent), as the main spec requires.
- No look-ahead: a signal uses only bars up to D's close; the entry is D+1's open.
- Reverse splits: Yahoo's adjusted history can lag a split (JAGX on 2026-11-23 had no bars for the split day
  and unadjusted history the next). *(Designer's call, from the builder check:)* a recorded split (Yahoo's split
  events, or an 8-K item 5.03 / 6-K naming one) is applied to the 50-session window. Without one, a session in
  the window is **split-suspect** only when the price jumps 2× or more overnight **and** that day's volume
  falls below the prior average (a reverse split shrinks the share count; a real spike like AKAN's multiplies
  volume). A split-suspect stock is skipped and counted. The runners stage does not use the Picks pipeline's
  `find_jumps` "unconfirmed" flag, which marks every move over 50%.

## Left to the builder

- The exact exclusion flags for funds, warrants, units and preferreds from the symbol directory.
- The spread estimator's implementation within the floor and cap.
- How the backtest reuses the training build's files (paths, chunking) within the weekly job's time budget.
- The page's styling, following the Day trade page.

## Testing

- Pipeline unit tests: the ignition rule (each threshold, the first-in-20 rule, split-suspect skips), the
  plan (stop rounding, gap skip, target), outcomes from daily bars (stop first on a two-touch day, gaps
  through the stop and target, hold-by), the spread estimate, warnings from fixture filing lists, the
  choose-then-confirm split of history, and the gate.
- Integration tests for the tables, RLS and repo.
- Web: Vitest for sizing and the gate label; Playwright for the page states (signals with warnings, no
  ignition, open runners, paper vs passed gate, a failed morning check).

## Owner steps before it runs live

1. Apply `0018_runners.sql` to the Supabase project before pushing the code that uses it.
2. The first weekly training job after the push writes the first backtest; until then the backtest card says
   "not run yet".
