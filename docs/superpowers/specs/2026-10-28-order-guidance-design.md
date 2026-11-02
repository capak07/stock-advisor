# How to place it: order guidance — design

**Status:** draft for the owner's approval, 2026-10-28.

## Why

The app says what to buy or sell but not how to place the order in Wealthsimple. A wrong order type costs money:
- a market buy of a small cap at the open can fill far above the last price;
- a fractional quantity can't be a limit order;
- a stop-limit can fail to fill in a gap.

The owner asked for the best approach to market, limit, stop-limit and recurring orders, for both buying and selling. The owner places orders both during market hours and in the evening.

## Goals

- **Every place that suggests a trade** shows one line headed **"How to place it"**:
  - the order type;
  - the quantity;
  - the price or prices, in the asset's own currency (US$ for US stocks and coins, C$ for TSX);
  - how long the order lasts.
- **Places:**
  - Today's Picks cards;
  - Watchlist Buy verdicts;
  - My Portfolio action cards (Sell, Trim, Add);
  - Invest lines, including BTC.
- **Each held stock shows its protective stop** as a stop-limit sell to keep in Wealthsimple. When the trailing stop has risen since the previous published run, it says "raise it from {old}".
- **The rules are Wealthsimple's real ones** (checked 2026-10-28, see Sources), and no line names an order the owner can't place.

## Non-goals

- Placing, changing or reading orders in Wealthsimple. There is no broker connection (spec non-goal).
- Intraday price forecasts. These are execution rules of thumb, and the page says so.
- Trailing-stop orders, which Wealthsimple doesn't offer. The app's trailing stop is kept by moving a stop-limit.

## Anti-goals

- Suggesting a limit order for a fractional quantity.
- A price in the wrong currency.
- Presenting a stop-limit as guaranteed protection.

## Wealthsimple's rules this design relies on (2026-10-28)

- **Stocks and ETFs:** market, limit, stop-market and stop-limit orders. Fractional quantities are market orders only.
- **A stop-limit expires at the close** by default. The expiry can be extended to 90 days.
- **Crypto:** market and limit orders. A limit order cancels after 24 hours unless extended, up to 90 days.
  - Stop orders appear only for some crypto accounts, and the help articles disagree, so the app says "if Wealthsimple offers it for this coin".
- **Recurring investments:** stocks, ETFs and crypto; daily, weekly, every two weeks or monthly.
  - Crypto is per the help centre's summary, not confirmed in the app, so the line hedges.
- **Bracket orders** (checked 2026-11-02, rolling out in phases):
  - A take-profit, a stop-loss or both on a **new** market or limit buy of **whole shares** of a US or Canadian stock or ETF. Fractional orders and shares already owned can't have one.
  - Both switch on only once the buy fully fills. When one executes it sells the shares and cancels the other.
  - They trade only in regular market hours. The stop-loss sells at market once hit, so in a gap it can fill lower.
  - Neither can be edited, only cancelled. Both lapse 90 days after the order is placed.

## The rules (a pure function; all numbers are the designer's calls, marked ★)

Inputs per line: side and kind (buy, add, sell, trim, stop, recurring), the last price (native), `atr_14_pct` (the daily range as a fraction), 20-day dollar volume, and the amount or quantity. Stops also need the stop price.

- **Buffer** ★: `b = clamp(0.25 × atr, 0.2%, 1.5%)`.
- **Liquid** ★: a 20-day dollar volume of at least 10M, the same line the cost rule uses.
- **Buy and Add:**
  - **Whole shares** = floor(amount ÷ price). When there's at least one: "**Limit buy {n} sh at {price × (1 + b)}**".
    - During market hours, "Day order"; in the evening, "set it to expire end of next trading day".
    - For a liquid stock, add "(a market buy is fine too, but avoid the first 15 minutes)".
  - **When the amount buys less than one share,** or a fractional remainder over C$25 ★ is left: "**Market buy C${amount}** (fractional: Wealthsimple fills fractions only as market orders; place it after the first 15 minutes)".
- **After a stock buy,** the protective stop: "**Then a stop-limit sell {n} sh: stop {stop}, limit {stop × (1 − s)}, expiry 90 days**", where `s = clamp(0.5 × atr, 1%, 5%)` ★.
  - It adds: "It won't fill if the price gaps below the limit. A stop-market sells in a gap at whatever price comes."
  - The stop is the pick's `stop`. For an Add it is the holding's trailing stop.
- **Sell** (stop hit, weak forecast or reversed signals): all shares.
  - "**Limit sell {n} sh at {price × (1 − b)}**, Day order".
  - For a liquid stock, "(a market sell is fine; this one needs out)".
- **Trim** ★: about a third of the shares, rounded down, at least 1.
  - "**Limit sell {n} sh at {price × (1 + b/2)}**, Day order. A trim isn't urgent, so ask a little above."
- **The holding's stop** (each held stock, on its action card and in the holdings table's note):
  - "Stop-limit sell {qty} sh: stop {trailing stop}, limit {…}, 90 days".
  - When the previous published run's stop was lower: "raise it from {old}".
- **Coins:**
  - Buy: "**Limit buy {amount} at {price × (1 + b)}**; it cancels after 24 hours unless you extend it". The ATR comes from candles where stored.
  - Stop: "If Wealthsimple offers a stop order for this coin: stop {trailing stop}…", otherwise "set a price alert at {stop}".
- **Bracket** (added 2026-11-02; picks, watched Buys and Adds, as an alternative after the steps above):
  - "**Or as one bracket order: limit buy {n} sh at {price × (1 + b)}**, {Day order or next trading day}, **take profit {price × (1 + q90)} ({+x%}), stop loss {stop} ({−y%})**". The percentages are against the limit price.
  - `n` is the same whole shares as the limit buy. Under one share, or for a coin, there is no bracket.
  - **The take-profit is the top of the forecast range (q90)** at the hold's horizon, applied to the entry price (the owner's choice, 2026-11-02). Leave it out when q90 is missing or not a gain. The range is an excess return against the benchmark, so a market move shifts it, and a note says so.
  - The stop-loss is the pick's stop. For an Add it is the holding's trailing stop, and the take-profit is the top of the holding's own range.
  - Notes:
    - the stop-loss sells at market;
    - a bracket can't be edited and lapses after 90 days, so to raise a trailing stop, cancel the bracket's stop-loss and place the stop-limit instead;
    - "It lapses before the {exit-by} exit-by; place a new stop then", when the exit-by is more than 90 days away;
    - when a fractional remainder is bought at market, the bracket covers whole shares only.
  - **An Add's bracket covers only the shares it buys.** Wealthsimple can't bracket shares already owned, so the held ones keep their stop-limit, and a note says so (the owner's choice, 2026-11-02). An Add with no trailing stop or exit-by gets no bracket.
  - **Not for Invest lines** (they have no stop), and not for plain Holds (no new buy to attach it to).
- **Recurring** (the Invest page's BTC share only): "**Or a recurring buy:** C${amount ÷ 4} weekly for 4 weeks ★ (Wealthsimple: daily, weekly, every two weeks or monthly)".
- **Prices** round to the cent at C$/US$1 or more, and to 4 significant figures below that, never in scientific notation (the existing `fmtPrice`).

## Where data comes from

- `atr_14_pct` and `log_adv20` are in `features_live` for forecast stocks. For holdings without a forecast, the run's stored features still have them when priced.
- Coins have no ATR stored, so the buffer falls back to 1% ★.
- The previous run's trailing stop comes from `holding_actions` of the previous published run.
- Market hours, for "Day order" against "next trading day": Toronto time, weekdays 9:30 to 16:00. Holidays aren't modelled ★, so the line says "in the evening" by clock only.

## Split (per the owner's standing preference)

- **Claude:**
  - `web/lib/orders.ts`, the pure rules with Vitest tests;
  - the loader additions: ATR and dollar volume on `PickView`, `HoldingAction` and Invest lines, plus the previous run's stops.
- **Cursor:**
  - the "How to place it" lines in the four places and the holdings-table note;
  - the e2e tests;
  - the docs.

## Sources

- Wealthsimple Help Centre, "Understanding order types" (stocks and ETFs): https://help.wealthsimple.com/hc/en-ca/sections/5624814354075-Understanding-order-types
- Wealthsimple, stop-limit orders and their expiry: https://help.wealthsimple.com/hc/en-ca/articles/4413542667675
- Wealthsimple, crypto order types: https://help.wealthsimple.com/hc/en-ca/articles/31804031644059-Choose-a-crypto-order-type
- Wealthsimple, recurring investments: https://help.wealthsimple.com/hc/en-ca/articles/9544942923547
- Wealthsimple, bracket orders (2026-11-01): https://help.wealthsimple.com/hc/en-ca/articles/57814660213147-Understanding-bracket-orders
