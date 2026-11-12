# Day Trade Skill Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show on the Day trade tab the same top 3 the owner gets by running the day-trader skill by hand at the open (strongest volume-confirmed breakouts among the most traded stocks), beside the existing after-costs top 3, with a track record for each.

**Architecture:** The pipeline freezes a `skill_rank` (1–3) on the first three signals by breakout strength, in the order cycles find them (the first full scan charts the 200 most-traded candidates, which is exactly the skill's set). The web page shows that list first, the after-costs list second, and a track record for both, before and after costs.

**Tech Stack:** Python 3.12, psycopg 3, pytest; Supabase Postgres; Next.js, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-10-day-trade-design.md`, amended by this plan's "Why" below (owner request, 2026-11-11).

## Why (owner, 2026-11-11)

On 2026-11-11 the skill's top 3 (FIS, ERAS, AFRM, ranked by breakout strength at 9:50) did well (two hit their targets) while the app showed only OGC.TO, because the app ranks by track record after the owner's 3.1% conversion cost and hides everything not eligible. The app had found the same three signals at the same prices. The owner wants the skill's ranking shown. Both rankings stay, each with its own record, so the data can say which is better.

## Global Constraints

- Breakout strength of a signal = `(entry / or_high − 1) × 100` percent (how far the trigger bar closed above the opening-range high). Computed from stored columns; not stored.
- `skill_rank`: 1–3, per day, set once and never changed or cleared. A cycle fills the day's free slots (lowest free rank first) with that cycle's NEW signals ordered by strength descending, then `trigger_at` ascending, then symbol. Signals of both markets and any eligibility count. A day has at most one signal per rank (unique partial index on `(day, skill_rank)`).
- The existing `rank` / `best_rank` (after-costs ranking), eligibility, costs, scan, replay and tracking are unchanged.
- Page order: status line; **"The skill's top 3"** (subtitle "The strongest volume-confirmed US breakouts at 10:00 AM ET, by how far the price is above the range high. Before your costs."); **"Top 3 after your costs"** (the existing section, existing no-trade line); other signals; track record; notes.
- Each skill card shows what the existing card shows, plus the strength ("+0.92% above the range high") and, for US stocks, the line "Your round-trip cost (currency conversion both ways plus the spread) is {cost_r}R: the trade must gain more than that to pay." Outcome lines show before and after costs ("+2.00R before costs, +0.64R after").
- Track record: two rows of figures for each window (20 and 60 trading days): "The skill's top 3" and "Top 3 after your costs"; each with count, target / stop / flat, average R before costs, average R after costs, sum after costs. Finished signals only. Label (replaces the old one): "Paper: what each list's trades would have done."
- Wording: no "buy"/"sell" advice; existing standing notes stay verbatim.
- New column: migration `0014_daytrade_skill_rank.sql`; RLS and grants already cover the table. All SQL in `store/repo.py`; web data only in `web/lib/data/*.ts`.
- Python tests via `pipeline/scripts/in-docker.sh`; `ruff check .`; LF line endings.

## Owner steps

- Apply `0014_daytrade_skill_rank.sql` to the Supabase project BEFORE pushing the code that uses it, and outside 9:30 AM–4:00 PM ET (a mid-session deploy fills that day's skill list from every signal already stored).

## Review Focus

1. A quiet first cycle (0 or 1 signals): later cycles fill the free ranks; filled ranks never move.
2. The afternoon job, or a manual restart, must not reassign or duplicate ranks already stored.
3. Two cycles racing is impossible (one job at a time), but a re-run of the same cycle must be idempotent.
4. A day with fewer than 3 signals all day: the page shows the ones there are.
5. Track record rows when one list has no finished signals.

---

### Task 1: Pipeline — freeze the skill ranking

**Files:** Create `supabase/migrations/0014_daytrade_skill_rank.sql`; Modify `pipeline/src/advisor/store/repo.py`, `pipeline/src/advisor/daytrade/cycle.py`, `web/e2e/db.ts` (seed helper accepts `skill_rank`; nothing else in web); Tests: `pipeline/tests/integration/test_schema.py`, `test_repo.py`, `test_daytrade_cycle.py`.

**Interfaces — Produces:**
- Column `daytrade_signals.skill_rank int check (skill_rank between 1 and 3)`, unique partial index `daytrade_signals_skill_rank on (day, skill_rank) where skill_rank is not null`.
- `repo.assign_skill_ranks(conn, day, ids: Sequence[int]) -> int` — in one transaction: reads the day's used ranks, gives the free ranks (ascending) to `ids` in order, skipping ids that already have one; returns how many it set. Never changes an existing rank.
- `cycle.run_cycle`: after storing a cycle's new signals, calls it with the new signals' ids ordered by strength desc, trigger_at asc, symbol asc.

- [ ] **Step 1: Failing tests:** schema has the column and index; `assign_skill_ranks` fills 1,2,3 in order, fills only free slots on a second call, ignores ids already ranked, is idempotent; a cycle with 5 new signals ranks the 3 strongest; a first cycle with 1 signal then a cycle with 4 → rank 1 from the first, ranks 2 and 3 from the second cycle's strongest; a job restart leaves stored ranks alone.
- [ ] **Step 2: Run** the touched tests — FAIL. **Step 3: Implement.** **Step 4:** PASS, plus all daytrade tests, test_schema.py, test_repo.py and `ruff check .`.
- [ ] **Step 5: Commit** `feat: freeze the skill's day-trade ranking`.

### Task 2: Web — show both lists and both records

**Files:** Modify `web/lib/daytrade.ts` (+ test), `web/lib/data/daytrade.ts`, `web/app/(app)/daytrade/page.tsx`, `web/components/daytrade/SignalCard.tsx`, `TrackRecord.tsx`, `web/e2e/daytrade.spec.ts`, `web/e2e/db.ts`.

**Interfaces — Consumes:** `skill_rank` (Task 1). **Produces:** `Signal.skillRank: number | null`; `strengthPct(s: Signal): number`; `strengthLine(s)`; `costHurdleLine(s)` (US only, else null); `outcomeLine` showing before and after costs; track-record summaries for both lists (`skill` = `skill_rank not null`, `costs` = `best_rank not null`) with average gross R and net R.

- [ ] **Step 1: Failing tests:** Vitest for `strengthPct`, the lines and the two-list record maths (incl. one list empty); e2e: a seeded day with 3 skill-ranked US signals and 1 after-costs TSX signal shows both sections in the stated order with the stated titles and subtitle, the strength and conversion lines, the before/after outcome; a day with skill signals but no eligible signal shows the skill list and the existing no-trade line; the track record shows both rows.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4:** vitest (all), tsc, eslint, full `npx playwright test` — PASS.
- [ ] **Step 5: Commit** `feat: show the skill's top 3 beside the after-costs top 3`.

## Amendment (owner, 2026-11-12)

On 2026-11-12 the app's skill list (NRG, TD.TO, TOST) differed from a hand run of the skill at 9:57 (VG,
NRG, ETSY). Three causes, each changed:

- The list was frozen at the first scan (9:50:30), before the 9:55 bar's signals (VG). It is now set from
  **10:00 AM ET** on (`SKILL_AT`): the first cycle at or after it ranks the signals found so far; later
  signals fill ranks still free.
- It ranked by the trigger bar's strength. It now ranks by how far the **last price** is above the range
  high (the entry stands in until a signal is tracked), as the skill's hand ranking does.
- It counted TSX signals; the skill scans US stocks only. The skill's list is now **US only**.
- VG's trigger was charted 22 minutes late because never-charted stocks took the whole chart cap.
  Re-checks of charted stocks whose new bar closed above their range high now get half the cap, oldest
  first; the never-charted get the other half (unused room flows either way).
