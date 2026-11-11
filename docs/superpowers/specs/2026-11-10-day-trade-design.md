# Day trade tab — design

**Status:** draft for the owner's approval, 2026-11-10.

## Why

The owner ran the day-trader skill pack (github.com/Jakeschincariol/day-trader-skill, MIT) by hand on
2026-11-09 and 2026-11-10: scan the market for opening-range breakouts, keep the volume-confirmed ones,
check their news, plan the stop and target, replay the trade, rank, and pick the top 3. They want the app
to do exactly that every trading day, on its own, and say when to enter and when to exit.

## What the owner decided (2026-11-10)

- **Schedule:** check every 5 minutes from 9:50 AM to 3:30 PM ET, every trading day, on its own.
- **Ranking:** by the replay's track record, not by breakout strength. When no signal has a positive record
  after costs, the tab says "no trade" instead of filling three slots.
- **Markets:** US and TSX. The owner converts CAD for each US trade (1.5% each way, the existing
  `usd_fx_fee_pct` setting), so US signals are ranked after a 3% round-trip cost; TSX signals pay no
  conversion.
- **No notifications, no orders.** Signals show in the tab only; the owner places trades by hand.
- A throwaway check (2026-11-10) confirmed GitHub's runners can read every Yahoo endpoint this needs.

## Spec amendment

The main spec (`2026-10-09-stock-advisor-design.md`) lists "intraday/day-trading signals" as a non-goal
and "no … day trading" as an assumption. This design amends both: **one Day trade tab of intraday
opening-range signals is in scope**, display only. Still out: order execution, broker integration, push or
email notifications, shorting, options, margin.

## What the tab does

### The rule (the skill's, unchanged)

- **Opening range:** the 9:30, 9:35 and 9:40 five-minute bars (high and low).
- **Entry signal:** the first completed 5-minute bar after the range that **closes** above the range
  high, with that bar's volume at least **1.5×** the range bars' average. One signal per stock per day.
- **Exit plan:** stop at the opening-range midpoint (rounded down to the cent), target at **2R**
  (R = entry − stop), and **flat by 3:55 PM ET** win or lose (12:55 PM on a 1:00 PM early close).
- **No new signals** after 3:30 PM ET (12:30 PM on an early close). Long only.

### Each cycle (every 5 minutes, 9:50 AM–3:30 PM ET)

1. **Scan** the universe for new signals: the skill's two stages (cheap closes for every stock, then real
   highs, lows and volume for candidates).
2. For each **new** signal: fetch the stock's last 60 days of 5-minute bars and run the **replay**
   (10,000 simulated rest-of-day sessions plus the same rule on every past session, as `trader-timemachine`
   does), and fetch its **headlines** (Yahoo, last 36 hours).
3. **Score** each signal after its cost (below) and **rank**; publish the top 3.
4. **Track** every signal already published today: has it hit the stop, the target, or neither yet?

### Cost and score

- **Cost a round trip, in percent:** US = 2 × `usd_fx_fee_pct` + `daytrade_spread_pct`;
  TSX = `daytrade_spread_pct`. New setting `daytrade_spread_pct`, default **0.10** (round trip).
- **Cost in R** = cost % × entry / (entry − stop) / 100.
- **Net history R** = the rule's average R on that stock's past sessions − cost in R.
  **Net replay R** = the replays' average R − cost in R.
- **Eligible** when: the rule fired at least **20** times in the stock's history, net history R > 0,
  and net replay R > 0.
- **Rank** eligible signals by net history R (ties: net replay R). Top 3 are shown; the rest are listed.
- A signal is **fresh** for 10 minutes after its trigger bar closes; after that the card says
  "late: the price has moved, this is a different trade" and shows the current price. Ranking keeps it.

### The page (`/daytrade`, in the left navigation after Invest)

- **Status line:** "Scanning · last update 10:35 AM ET · next ~10:40" / "Market closed" / "Before 9:50 AM:
  the opening range is still forming" / "Today's scan failed: <reason>".
- **Top 3 cards**, each: symbol, name, market chip (US/TSX); the signal ("Entry signal 10:10 AM at
  $67.65"), fresh or late; **Stop**, **Target**, **Flat by 3:55 PM**; replay odds (target first / stop
  first / neither, green at close); history line ("This rule on TGTX's last 55 sessions: fired 37 times,
  5 target, 20 stop; average −0.12R before costs"); cost line ("Cost 3.10% round trip = 0.53R"); shares
  sized to the owner's max loss per trade (below); up to 3 headlines; and the live status once tracked
  (open / target hit / stopped out / flat at close, with the R).
- **No trade:** "No signal today has a positive record after costs (N signals checked)." The rest are
  still listed below.
- **Other signals today:** a table of every signal with its net R values and why it isn't top 3.
- **Track record:** every published top-3 signal's outcome over the last 20 and 60 trading days: count,
  target / stop / flat, average net R, and the sum. Labelled "paper: what the rule's trades would have
  done, after costs".
- **Standing notes:** not financial advice; nothing is ordered; "frequent day trading in a TFSA can be
  treated as a business, which makes the gains taxable (not tax advice)"; data are Yahoo's free 5-minute
  bars and can lag a few minutes.
- The page refreshes itself every 60 seconds while the market is open.

### Settings (existing Settings page)

- **Max loss per trade (CAD)**, default 50. Shares = floor(max loss in the stock's currency / R), with US
  converted at the latest USD/CAD. Shown as "≈ N shares (risking ≈ C$X at the stop)". The card says when the
  stop is too far for even one share.
- **Day-trade spread (round trip %)**, default 0.10.

## How it runs

- **Workflow `daytrade.yml`:** two jobs a day, **morning 9:35 AM–12:40 PM** and **afternoon 12:35 PM–3:59
  PM ET** (a GitHub job is limited to 6 hours), each started by `workflow_dispatch` from Supabase
  `pg_cron` + `pg_net` with the token from Vault, as in `supabase/manual/run_dispatch_cron.sql` (both DST
  times; a guard checks the ET clock and the NYSE/TSX calendars). The job loops: wait for the next 5-minute
  bar to close (+ 30 s for Yahoo to catch up), run one cycle, repeat. The afternoon job also finalizes the
  day at 3:55 PM (flat-by outcomes). `concurrency` keeps one job at a time.
- **Scan budget:** the full universe (about 5,900 US + TSX listings from the existing symbol lists) is
  scanned at 9:50 and every 15 minutes after; the cycles in between re-check only that day's candidates
  (charts that are near or above their range high). The skill measured about 4 minutes for a full US scan;
  a cycle that runs long skips to the next bar rather than queueing.
- **Code:** a new `pipeline/src/advisor/daytrade/` package ports the parts of the skill's `scan.py`,
  `entry.py`, `exit.py`, `timemachine.py` and `news.py` that this needs (credited, MIT), with tests built
  on the skill's saved fixtures where they fit. All SQL in `store/repo.py`.
- **Failure:** a failed cycle is recorded and the next one runs; a job that dies leaves the page saying
  when the last update was. GitHub's failure email covers a dead job (as today).

## Data

Migration `0013_daytrade.sql`, pipeline tables with the usual RLS and grants:

| table | holds |
| --- | --- |
| `daytrade_days` | one row per ET date: status, cycles run, last update, symbols scanned, usable, candidates, error |
| `daytrade_signals` | one row per (date, symbol, market): trigger time, entry, opening-range high/low, stop, target, volume ×, cost %, replay stats, history stats, net R values, eligible, rank (1–3 or null), headlines (jsonb), status (open/target/stop/flat), exit time and price, gross and net R |

Settings gain `daytrade_max_loss_cad` and `daytrade_spread_pct`. Kept 400 days.

## Non-goals

- Orders, broker connections, notifications of any kind.
- Shorting, options, margin.
- Changing Picks, Invest, forecasts or the stock model.
- TSX Venture.

## Risks the owner accepted

- The rule has no proven edge: on 2026-11-10 it averaged about −0.1R per trade before costs on the three
  stocks checked. "No trade" may be the usual answer, and the track record will show whether that changes.
- Yahoo is free and unofficial: it can lag, change or start throttling; a whole day can go without data.
- TFSA: the CRA can treat frequent trading in a TFSA as a business.

## Testing

- Pipeline unit tests for each ported piece against the skill's fixtures (scan stages, entry trigger with
  volume, exit plan, replay with a fixed seed, cost and score, ranking, tracking to target/stop/flat, the
  cycle schedule including early closes and DST); integration tests for the tables and repo; a workflow
  test for the two jobs and the guard.
- Web: Vitest for sizing and formatting; Playwright for the page states (scanning with a top 3, no trade,
  late signal, market closed, failed day) and the track record.

## Owner steps before it runs live

1. Apply migrations `0012_holding_monitor.sql` and `0013_daytrade.sql` to the Supabase project.
2. Put a GitHub fine-grained token (this repo only, "Actions: Read and write") in Supabase Vault, then run
   the day-trade dispatch SQL this build adds (the same token serves the run-trigger file).
3. Apply `0014_daytrade_skill_rank.sql` to the Supabase project BEFORE pushing the code that uses it, and outside 9:30 AM–4:00 PM ET (a mid-session deploy fills that day's skill list from every signal already stored).
