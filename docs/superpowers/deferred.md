# Deferred work

These are items that the Plan 1, Plan 2a, Plan 2b, Plan 2c, Plan 2d, Plan 2e and Plan 2f reviews deliberately pushed to later plans. Each later plan must pick up its section before it is called done. The spec stays the authority; this list only records what earlier plans did not do.

## Plan 2g: 13F institutional ownership

- **Source 11 (SEC 13F data sets plus OpenFIGI CUSIP mapping) moved out of Plan 2d.** It needs a persistent CUSIP → ticker map (about 6,500 CUSIPs, roughly 27 minutes at OpenFIGI's keyless 25 requests a minute, then only new CUSIPs each quarter) and about 100 MB of quarterly SEC data sets. Research: `.superpowers/research/plan-2b/sec.md` §5. Fixtures: `.superpowers/research/plan-2c-fixtures/sec/13f_*` and `openfigi_cusip_mapping_sample.json` (git-ignored).

## Plan 2h: options, catalysts and Canadian short positions

- **Split out of Plan 2e**, which kept macro, crypto and on-chain. Sources: Yahoo option chains (18) and CBOE put/call ratios (19); openFDA (48), ClinicalTrials.gov (49), USAspending.gov (50) and House Clerk periodic transaction reports (51); the Canadian short-position report (15), kept only if a keyless file is confirmed.
- **Catalysts name companies, not tickers:** drug sponsors, trial sponsors and contract recipients need a company-name → symbol map for both markets. Plan 2f built one; reuse `advisor.company_names` and `advisor.news.mapping.TickerMap`.
- **House Clerk reports are PDFs.** Check that electronically filed reports read as text before committing to source 51.

## Plan 2i: social and attention

- **Split out of Plan 2f**, which kept news. The sources are:
  - ApeWisdom mention counts (44);
  - Google Trends (46), best-effort, at most 50 symbols, holdings first;
  - Wikipedia pageviews (47).

  Reddit RSS (43) and StockTwits (45) are dropped because their terms forbid automated access. Research: `.superpowers/research/plan-2f/social.md`.
- **Wikipedia needs a ticker → article map.** Build it once from Wikidata, commit it, and refresh it now and then; don't query SPARQL at run time. In Wikidata the ticker is qualifier P249 on stock exchange P414, with Nasdaq Q82059, NYSE Q13677 and TSX Q818723.
- **Wikimedia's User-Agent policy** asks for contact information. A project URL meets it, so use the repo's URL, never an email.
- **Collectors covering both stocks and crypto** (ApeWisdom; LINK, SOL and COMP exist as both): keep the asset types apart in symbol lists and cache keys before the first such collector. Plan 2e's crypto sources and Plan 2f's news sources keep them apart already.

## Plan 3: model and features

- **Unconfirmed jumps in the wild:** the first live run flagged an unconfirmed jump somewhere in the 100-day window for about 4.7% of priced symbols. Check what they are (microcaps, biotech, bad data) before building the jump feature.
- **TSX universe size:** the live TMX filter keeps about 675 TSX symbols, while spec §4.3 says about 1,500. Update the spec's number.
- **Jump indicator feature** (spec §10). Plan 2b keeps flagged bars and records `unconfirmed_jump` for the latest bar of each priority symbol. Plan 3 turns flagged days into the jump feature and blocks a Buy on them (§6.1). A bad first bar in a window is never flagged, because there is no earlier close to compare.
- **Exclude non-common instruments before any pick exists:**
  - ETNs with `ETF=N` (AMUB, BDCZ, DGP and others);
  - structured trusts (GJH, JBK, KTN);
  - CHSCN (a preferred);
  - Empire State Realty OP units.

  Use yfinance `quoteType` from sector mapping. Closed-end funds are an owner decision. Run the same check on TSX symbols, for income trusts and closed-end funds whose names the TMX filter cannot recognise.
- **Partial current-day bar** at the pre-close run, from Yahoo. Features must treat today's bar as incomplete.
- **Benchmarks** (SPY, XIU.TO, sector ETFs) need a distinct asset type. Otherwise `upsert_symbols` deactivates them.
- **Data quality:** `adv20` on histories shorter than 20 bars, and clamping `DailyBar` high/low inconsistencies.
- **Analyst rotation:** `max_symbols` always takes the head of the missing list. Rotate the rest oldest-first, so the bottom of the analyst shortlist isn't left unfetched forever.
- **Earnings failure rate:** measure the first live run's per-symbol failure rate for `yfinance_earnings`.
- **Yahoo analyst throttling.** Three local full runs on 2026-10-14 got analyst data for 39 of 200, then 199 of 200, then none (`SilentFailure`, served stale). Each came right after the bulk price download from one busy IP. Fetched alone, 40 of 40 large caps had data, and earnings data was unaffected. If GitHub Actions runs show the same, fetch analyst data apart from the price download: in the 06:30 ET health job, or for priority symbols before prices.
- **XBRL facts are raw.** `sec_xbrl` keeps every listed concept and every re-reported or restated duplicate with its `filed` date. Features pick a concept per period by `METRICS` priority, take the latest fact filed on or before `as_of`, derive Q4 as FY minus 9M, and compute single quarters of cash-flow items from year-to-date facts (research `sec.md` §2.4–2.5).
- **Insider and holder signals.** Count only codes P and S from non-derivative rows for insider buying and selling, and treat `planned` (10b5-1) sales as weaker. For 13D/G, a 0-share 13G/A can be an index giant's entity realignment rather than an exit.
- **Amendments:** a Form 4/A restates trades already in the original Form 4, and both are stored (`form` tells them apart; the XML doesn't name the original's accession). Count a trade once: for the same owners, trade date, code and shares, keep the latest `accepted_at`. Do the same for 13D/G amendments of one reporting person.
- **FRED dates are observation dates.** A month's CPI and unemployment rate are published about two weeks into the next month and are later revised. Backtests must apply release lags; point-in-time vintages (ALFRED) need a key.
- **Crypto history:** Coinbase gives 290 finished daily USD candles per coin in one request. Since Plan 5c the history stage pages back a year (and to the first buy) for held coins with `history.fetch_coin_closes`; watched coins still get 290 days. 12-month momentum needs 365, so page watched coins too when the crypto model needs it. Altcoins are measured against BTC (spec §5.4), so price BTC whenever any crypto is held or watched.
- **Macro event:** "days to the next FOMC decision" comes from the `fomc` source's `meeting` records. The decision is at 14:00 ET on the meeting's last day.
- **Protocol TVL** (spec source 52 names chain and protocol TVL): Plan 2e collects chain TVL only. DeFi tokens such as UNI or AAVE belong to a protocol rather than a chain, and DefiLlama's `/protocols` list has a `symbol` per protocol. Add it if the crypto model's features need it.
- **HY spread history:** FRED's `BAMLH0A0HYM2` CSV only goes back to 2023-10-16 (ICE licensing), so an 8-year backtest can't use it as is.
- **Training histories:** the live collectors keep 30–60 days. Full histories exist: alternative.me `limit=0` (from 2018), DefiLlama's full chain series, and blockchain.com `timespan=all`. FOMC meetings older than the calendar page's 5 or so years are on `fomc_historical.htm`.
- **News features are live only** (spec §5.1). The news stage merges them into each asset's `features_live` row: `news_stories_48h`, `news_outlets_48h`, `news_sentiment_mean`, `news_sentiment_trend` and `news_volume_z`. The volume z-score has a value only after 5 days of stored news.
- **News matching quality:**
  - Market-wide items match targets by name.
  - One-word everyday names (`COMMON_WORDS`) count only with a tag or cashtag.
  - Google News and Yahoo items count only for the stock they were fetched for.

  Measure false matches on a week of real `news_items`, then tune the word list and the cap of 3 stories per outlet. Known gaps from Plan 2f's reviews:
  - Short forms are missed: "Amazon" (short name "Amazon.com"), "Meta" ("Meta Platforms"), "Nvidia" (the directory says "NVIDIA").
  - Some one-word names still match ordinary words: "Arm", "Dover", "Carnival", "Mosaic", "Oracle of Omaha". "Bitcoin, Gold, Stocks Rally" reads as the coin Bitcoin Gold.
  - `outlet_key` joins "MarketBeat" and marketbeat.com, but not "Yahoo Finance" and finance.yahoo.com or "The Motley Fool" and fool.com, so those publishers can fill 6 of an asset's stories, not 3.
  - **Brokers' own news is mostly their analysts' calls.** On the 2026-10-16 live run, 5 of RY.TO's 30 stories were RBC rating other companies, for example "Moody's (NYSE:MCO) Price Target Cut to $575.00 by Analysts at Royal Bank Of Canada" and "Royal Bank of Canada cuts target for Lockheed Martin stock". All five scored between −0.21 and −0.94, which drags the bank's sentiment down. Per-stock items skip the mapping's analyst-verb rule. Drop them when the stock's own name is the analyst ("by Analysts at <name>", "at <name>" after a rating change, "<name> cuts target for …"). This matters for RY, TD, BMO, BNS, CM, GS, MS and JPM.
- **News volume z-score:** unbounded on sparse history. Daily counts of [0, 0, 0, 0, 1] and 10 stories today give about 24.5. Clip it or floor the spread before a model uses it.
- **Missing versus zero:** when no news item came in at all (every news source failed), the run leaves the `news_*` features missing. When items came in but none for an asset, its counts are 0 and its sentiment is empty. Treat missing as unknown.
- **`features_live` rows:** `merge_features_live` creates a row with only `news_*` keys for a shortlisted stock that had no row. A later plain `write_features_live` for the same run and asset would hit the unique key, so merge there too, or write before the news stage.

## Plans 4 and 5: recommendations and dashboard

- **Price history (Plan 5a):** `daily_closes` and `fx_rates` feed the charts and CAD values.
  - Stock closes are adjusted for splits and dividends, so returns from them are total returns, and the latest close is the actual price.
  - Coin closes are in USD; convert them, and US holdings, with the `fx_rates` row of the same day (the latest one for today's value).
  - The run summary's `history` says what was stored, backfilled, rescaled after a split, or missed.
  - Plan 5b values holdings and charts portfolio returns from them; the ticker chart (Plan 5c) reads them too.

- **Dashboard before the model (Plan 5b):** the portfolio shows values, P/L, returns, warnings and a breakdown by market and account.
  - Waiting for `holding_actions` and picks (Plan 4): action cards, likely ranges, trailing stops, exit dates, risk levels, the breakdown by risk and the max-size warning. The holdings table places its cells by class, so these columns can be added.
  - Waiting for data no plan collects yet: the sector warning (`symbols.sector` is never filled; a fundamentals plan should fill it) and the note on US dividend payers in a TFSA.
  - The status bar's Paper badges are static until picks are graded live (Plan 4). The missed-slot notice and the next run's time need the schedule in TypeScript; Plan 5c left them for the dashboard plan after the model.
  - Waiting for the model (Plans 3 and 4): Today's Picks, Track record, the watchlist's verdict columns, and the Ticker page's forecast cone, top factors, catalysts and past picks (Plan 5c shows an empty card in their place).
  - Trades are corrected by deleting them in the trade list and adding them again (Plan 5c); there is no edit. Deleting also sidesteps the NOT VALID `*_usd_needs_fx_rate` check that blocks updating old USD rows.
- **Portfolio returns (Plan 5b):** time-weighted. A day's buys count from the start of that day and its sells at the close, so a buy at the close dilutes that day's return slightly; counting buys at the close instead would let a large buy into a small position show a huge return. Trades on days without a close count on the next trading day, an asset with no closes at all is valued at cost, and before its first close (a coin bought before Coinbase listed it) at that first close, so its early gain lands on the buy day.
- **Coin values (Plan 5b):** from Coinbase's USD closes at the Bank of Canada rate, the same source as the chart, not CoinGecko's CAD quote in `features_live`.
- **Unlisted stocks (Plan 5b):** a held stock Yahoo can't price leaves every run degraded, so the buy form asks for confirmation when a stock isn't in the US or TSX lists (ETFs aren't). The watchlist accepts them with a note, and a file import leaves them out unless the owner ticks them in (Plan 5c).
- **File import (Plan 5c):** one broker CSV at a time, all or nothing, at most 5,000 trades. Rows are matched against recorded trades by side, account, symbol, day, quantity and price, so re-importing a file adds nothing, but two identical trades on one day in one file count once. Dividends, transfers and fees are left out: the ledger has no cash.
- **Ticker sources (Plan 5c):** `source_health` has one row per source per run, not per symbol, so the Ticker page says which sources that cover the asset *answered* in the run, not which returned records for that symbol. Per-symbol contribution needs the collectors to report symbols.

- **Crypto Buy and Add:** a coin whose `unconfirmed_price` is true (Coinbase and Kraken more than 2% apart on the latest day) is blocked like a stock's `unconfirmed_jump`. `None` means Kraken had no close to compare, and crypto gets no jump rule (`find_jumps` isn't applied to Coinbase candles), so a coin only Coinbase lists has no price sanity check: treat `None` as unconfirmed, or apply the jump rule to crypto.
- **Crypto currency:** Coinbase candles, and so ATR and the highest close since purchase, are in USD, while lots and `price_cad` are in CAD. Stops, trailing stops and graded returns must use one currency: convert the candles with the Bank of Canada FXUSDCAD rate (`boc_valet`) or CoinGecko's CAD/USD ratio, or work in USD with the entry converted at the buy date's rate.
- **Crypto quote age:** each crypto row carries `quote_updated_at` and `quote_stale` (older than a day, e.g. served from cache). Show the age next to a stale CAD value.
- **Watchlist coins:** check a coin with CoinGecko when it is added. A coin CoinGecko doesn't price is only listed in `crypto_unquoted`; it doesn't degrade the run.
- **Source credits:** CoinGecko requires "Data provided by CoinGecko" wherever its data is shown, and FRED asks to be cited. alternative.me, DefiLlama and blockchain.com welcome a credit. The dashboard footer credits Yahoo Finance, Coinbase and the Bank of Canada (Plan 5b); add each source when a page first shows its data.
- **`runs.summary`** gained `crypto` (held and watched coins) and `crypto_unquoted` in Plan 2e, and `news` (items, stories, rows, assets, sentiment status) in Plan 2f.
- **News text is untrusted:** titles, outlets and links come from third-party feeds. Render them as text, never as HTML. `parse_feed` keeps only http and https links.
- **Sentiment status:** the scheduled run installs the `nlp` extra. So `summary.news.sentiment` reading `unavailable` means a broken install, and `failed: …` a model or scoring error. The run still publishes in both cases; Source health shows the reason (Plan 5c).
- A table for holding-action outcomes. Spec §6.5 grades holding actions, but §8 has no table for them.
- Decide spec §7.2 ("holdings analysis survives a later failure") against "failed runs are never published".
- A `published_runs` view, so the dashboard never reads unpublished rows.
- Show missed or dropped schedule slots on the dashboard.
- An index on `picks.run_id`, added with its first reader (`source_health.run_id` got one in Plan 5c).
- **Old USD lots and sells:** pre-rev-2 USD lots and sells have no `fx_rate_cad`, and the `*_usd_needs_fx_rate` check (NOT VALID) still applies on UPDATE. Editing such a row fails until a rate is backfilled. Backfill from Bank of Canada rates first.
- **Failed-run counts:** a failed run's per-market `priced` and `fresh` count only priority symbols.
- **`runs.summary` shape:** it changed in Plan 2b, from flat keys to `{"markets": {"US": …, "TSX": …}, …}`. The dashboard must read both shapes, or ignore runs from before the change.
- **Run summary `shortlist`:** the per-market `shortlist` excludes priority symbols but the top-level `shortlist` includes them. Rename one before the dashboard shows them side by side.

## Operational and minor

- **yfinance cache lock:** yfinance's timezone cache sometimes reports "database is locked" during a threaded download and drops a symbol. It hit RY.TO in phase 1 of the 2026-10-16 live run (phase 2's retry priced it) and SPY in Plan 5a's backfill (the next run fetched it). If it recurs, give yfinance a per-run cache folder or download without threads.

- **Breaker and deadlines:** a `DeadlineExceeded` failure counts toward the circuit breaker.
- **Stale versus partial:** a call whose fetched symbols all fail while the window served the rest reports STALE, not PARTIAL, and counts toward the breaker.
- **Run deadline:** it starts in `execute_run`, after job setup. Consider a 28-minute budget if runs approach the 40-minute kill.
- **FINRA symbol-key twins:** `BRK.B` and a plain `BRKB` share one key, and the later request wins silently.
- **No markers on PARTIAL:** a PARTIAL result writes no empty markers, so uncovered symbols are refetched while any symbol keeps failing. This costs capped slots.
- **Old shortlist default:** remove the `SHORTLIST_SIZE = 300` default and the unused `shortlist()` helper in `enrich.py`, or require an explicit size.

- **Deploy-time probe:** check that the `advisor_pipeline` login really cannot write holdings or run DDL on Supabase, and that Supavisor accepts the `advisor_pipeline.<project-ref>` user.
- **Run sweep:** sweep abandoned runs using SQL `now()` instead of the Python clock or `--now`, and move the sweep and state loading inside `execute_run`'s try.
- **Workflows:**
  - No-op cron runs re-save an identical Actions cache.
  - The `pipeline-run` concurrency group can cancel an older pending job.
- **Migrate CLI:** refuse `--baseline` once `schema_migrations` has rows, print the names it baselined, and take an advisory lock.
- **Dev machine:** a `uv` re-sync can fail with "Access is denied" on `.venv` under OneDrive. Use `uv run --no-sync ruff check .` for lint.
- **SEC document cache** (`<cache>/sec-documents/`) grows by roughly 1 MB a day of Form 4 and 13D/G XML; prune files older than 400 days.
- **XBRL bandwidth:** company facts are downloaded daily for every US symbol in the enrichment list (about 300 KB compressed each). If time or bandwidth becomes a problem, refresh a company only when its submissions show a new 10-K or 10-Q.
- **8-K bodies** (Exhibit 99.1 earnings text) are not downloaded; only the item codes are used.
- **SEC first fill:** the first live run fetched Form 4 documents for 42 of 299 US symbols (budget 1,000) and 13D/G for 122 (budget 500), so those two sources stay PARTIAL for about 5 and 3 runs (a second run added 67 and 110 symbols; 13D/G finished on the third, when Form 4 reached 188 of 300). Raise the budgets for the first deployment if that is too slow.
- **Unparseable SEC documents** are skipped and dropped from the cache, so every run downloads them again (one budget unit each) and nothing records the skip. Count skips into the source-health detail if they ever appear.
- **SEC client polish:** `filings()` returns the shared list (return a tuple); untested: a 403 through `get()` end to end and `DocumentBudget`'s deadline check. `sec_xbrl` copies every fact even for a company's first share class, and one malformed fact fails that symbol rather than being skipped.
- **SEC outage guard edges:**
  - It is one failure counter for both SEC hosts. If www.sec.gov (documents and the ticker map) is down while data.sec.gov answers, successes there keep resetting it, and Form 4 and 13D/G fail symbol by symbol.
  - A ticker map that answers 200 with a broken body is downloaded again for every symbol.
  - In the health job, a thread waiting on another's fetch shares that fetch's deadline outcome, not its own 120 s budget.
  - A single-flight error is re-raised in several threads, so its printed traceback mixes frames.
  - `DocumentBudget` charges a unit for a download that then fails.
  - Untested: that a timeout counts, that a 404 resets the counter, and that `DeadlineExceeded` does neither.
- **Form 4 details:** a reporting owner's name can be empty; `acquired` is False when the A/D code is missing; no unit test covers rows skipped for a missing code, share count or date.
- **Runner coverage:** no runner-level test of a PER_RUN source (such as `sec_8k`) falling back to its cache within `freshness`.
- **CoinGecko's keyless limit** is unpublished and shared per IP, and GitHub's runners share IPs. The source makes one call per run, with one retry after Retry-After. If 429s become common, holdings are valued from a quote cached within 2 days and the run is degraded. The health job refreshes only BTC, so after a weekend other held coins' quotes are older than that: they are listed in `crypto_unquoted` and the run is degraded. A free Demo key would need an account, which R7 rules out.
- **Terms to watch:**
  - FRED's FAQ says "Don't do any data mining, scraping or extraction of FRED data", while its terms forbid only disruptive scraping. The pipeline makes 9 requests a day, cached for the day, for personal use.
  - CNN's terms allow downloads "for your personal use only". Its endpoint is unofficial: it answers plain clients with 418 "You're a bot", and the pipeline gets past that by sending CNN's own Referer and Origin. Drop the source if that isn't acceptable.
  - CoinGecko's terms forbid storing its data beyond a cache refreshed daily; only each run's features keep a quote.
- **blockchain.com** documents a newer gateway API, so the legacy `api.blockchain.info/charts` endpoints used here may be retired.
- **FOMC calendar** is read from the page's `fomc-meeting__month` and `fomc-meeting__date` classes. A redesign makes the source PARTIAL; releases still arrive.
- **Market-wide partial results** are neither cached nor backfilled per series. FRED is the first core source of this kind: a series that fails is absent for that run even if yesterday's cache has it, and the run is degraded.
- **Google News from GitHub's IPs:** about 400 queries per run, one a second. A bot check or a 429 stops the source for the rest of the run, with holdings asked first, and the run is degraded because the source is core. If that happens often, query only holdings, watchlist and the top of the shortlist. Its robots.txt disallows `/rss/search`; the owner accepted that on 2026-10-16.
- **News sources dropped in Plan 2f.** Research: `.superpowers/research/plan-2f/`. Protos replaces the dropped crypto feeds.
  - Terms forbid automated access or storing: Seeking Alpha, Investing.com, Financial Post, CoinDesk, Cointelegraph.
  - No working keyless feed: Benzinga (Cloudflare), GlobeNewswire (Akamai 403), Business Wire (no public feed), CNW (its RSS is gone, and its news sitemap isn't a feed).
- **Short feed windows:** PR Newswire keeps about 90 minutes of releases and Newsfile 10 per industry, so two runs a day miss most of them. Google News, searched by company name, covers the important ones.
- **BNN's dates:** it stamps UTC clock times with -0400 (`clock_is_utc`). Recheck if BNN fixes its feed: a correct offset would then put its items 4 hours early.
- **FinBERT cost:**
  - The `nlp` extra adds about 900 MB to the run's install (CPU PyTorch and transformers, from the uv cache), and the model about 440 MB (an Actions cache keyed on its revision).
  - Loading the model takes about 25 s on a cold cache.
  - Its CC BY-NC-SA 4.0 licence allows personal use only.
- **news_items growth** (measured on the 2026-10-16 live run):
  - The first run stored 7,206 rows for 403 assets, from 10,846 items. That's 4.1 MB, about 590 bytes a row with indexes; Google's links average 240 characters.
  - Later runs add only stories they haven't stored, estimated at about 1,800 a run. Over the 90-day prune that's roughly 230,000 rows and 130 MB, a quarter of Supabase's free 500 MB.
  - If space gets tight, prune news after 30 days. The volume z-score needs only 21.
- **Unscored duplicates:** say a story was stored unscored (scoring was skipped or failed), and a later run sees it under another item's key. That run doesn't write the row again, so the sentiment stays empty.
- **Company names:** on 2026-10-16, `search_name` was checked against the full NASDAQ Trader and TMX directories (6,645 names). If Google News finds nothing for a holding, check its directory name: an unusual suffix leaves a quoted query that matches nothing.
