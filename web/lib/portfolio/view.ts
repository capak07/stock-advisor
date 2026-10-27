import { fmtMoney } from '../format'
import { tradeCurrency } from '../symbols'
import type { HoldingAction } from './actions'
import { buildLedger, positionKey } from './ledger'
import type { FxRate, FxRates, PriceBook } from './lookup'
import { PERIODS, growth, periodReturns, type Period, type PeriodReturns } from './returns'
import { ACCOUNT_LABELS, assetKey } from './types'
import type { Account, AssetType, Close, Currency, Market, Trade } from './types'
import {
  breakdown,
  byRisk,
  sectorWarnings,
  taxableEstimate,
  totals,
  valueHoldings,
  type Slice,
  type Totals,
} from './valuation'
import { superficialLossWarnings, tfsaWarnings, type TfsaGuideline, type Warning } from './warnings'

export interface Note {
  text: string
  /** Shown with a warning icon. */
  warn: boolean
}

export interface HoldingRow {
  key: string
  account: Account
  symbol: string
  name: string | null
  market: Market | null
  valueCad: number
  gainCad: number
  gainPct: number
  /** The latest run's action; null for a holding bought after it, or before the first. */
  action: HoldingAction | null
  notes: Note[]
}

/** What the sell form offers: each open position at average cost. */
export interface SellOption {
  key: string
  account: Account
  symbol: string
  assetType: AssetType
  qty: number
  costCad: number
  currency: Currency
  /** The latest stored close in the trade currency, or null when there's none (or, for a coin, no rate). */
  lastClose: Close | null
}

export interface PortfolioView {
  totals: Totals
  /** Accounts with an open position, as labels. */
  accounts: string[]
  fx: FxRate | null
  firstBuy: string | null
  /** Null until there are two trading days to draw. */
  periods: Record<Period, PeriodReturns> | null
  holdings: HoldingRow[]
  warnings: Warning[]
  byMarket: Slice[]
  byAccount: Slice[]
  byRisk: Slice[]
  sellable: SellOption[]
}

export interface PortfolioInputs {
  trades: Trade[]
  prices: PriceBook
  fx: FxRates
  names: Map<string, string>
  guideline: TfsaGuideline
  /** The holding actions of the newest published run that has any. */
  actions: HoldingAction[]
  /** Stock sectors by symbol (`symbols.sector`). */
  sectors: Map<string, string>
}

/**
 * The latest close in the currency the asset trades in. Coinbase closes are in USD, but coins
 * trade in CAD: a coin's close converts at the latest rate, or is null without one.
 */
function lastClose(p: { assetType: AssetType; symbol: string }, prices: PriceBook, fx: FxRates): Close | null {
  const close = prices.latest(assetKey(p.assetType, p.symbol))
  if (close === null || p.assetType !== 'crypto' || close.currency === 'CAD') return close
  const rate = fx.latest()?.usdCad
  return rate === undefined ? null : { day: close.day, close: close.close * rate, currency: 'CAD' }
}

/** Everything the portfolio page shows: values, returns, the model's actions and the checks (spec §7, §9). */
export function portfolioView(
  { trades, prices, fx, names, guideline, actions, sectors }: PortfolioInputs,
  today: string,
): PortfolioView {
  const ledger = buildLedger(trades, fx)
  const valued = valueHoldings(ledger.positions, prices, fx).sort((a, b) => b.valueCad - a.valueCad)
  const lossWarnings = superficialLossWarnings(ledger.sales, trades, today)
  const warnings: Warning[] = [
    ...ledger.problems.map((problem) => ({ title: 'A trade was left out', detail: problem })),
    ...tfsaWarnings(ledger.sales, guideline, today),
    ...lossWarnings,
    ...sectorWarnings(valued, sectors),
  ]
  const actionOf = new Map(actions.map((a) => [positionKey(a), a]))

  const holdings = valued.map((h): HoldingRow => {
    const action = actionOf.get(positionKey(h)) ?? null
    const notes: Note[] = []
    if (h.priceCad === null) notes.push({ text: 'No close yet; at cost', warn: true })
    for (const w of lossWarnings) if (w.symbol === h.symbol && w.note) notes.push({ text: w.note, warn: true })
    const taxable = taxableEstimate(h)
    if (taxable !== null) notes.push({ text: `Taxable: est. ${fmtMoney(taxable, { signed: true })}`, warn: false })
    for (const text of action?.warnings ?? []) notes.push({ text, warn: true })
    return {
      key: positionKey(h),
      account: h.account,
      symbol: h.symbol,
      name: names.get(h.symbol) ?? null,
      market: h.market,
      valueCad: h.valueCad,
      gainCad: h.gainCad,
      gainPct: h.gainPct,
      action,
      notes,
    }
  })

  const g = growth(trades, prices, fx)
  const periods =
    g && g.days.length >= 2
      ? (Object.fromEntries(PERIODS.map((p) => [p, periodReturns(g, p)])) as Record<Period, PeriodReturns>)
      : null

  const accounts = [...new Set(valued.map((h) => h.account))].map((a) => ACCOUNT_LABELS[a])
  const firstBuy = trades.filter((t) => t.side === 'buy').reduce<string | null>((min, t) => (min === null || t.day < min ? t.day : min), null)

  return {
    totals: totals(valued),
    accounts,
    fx: fx.latest(),
    firstBuy,
    periods,
    holdings,
    warnings,
    byMarket: breakdown(valued, 'market'),
    byAccount: breakdown(valued, 'account'),
    byRisk: byRisk(valued, actions),
    sellable: [...ledger.positions]
      .sort((a, b) => a.symbol.localeCompare(b.symbol) || a.account.localeCompare(b.account))
      .map((p) => ({
        key: positionKey(p),
        account: p.account,
        symbol: p.symbol,
        assetType: p.assetType,
        qty: p.qty,
        costCad: p.costCad,
        currency: tradeCurrency(p.assetType, p.symbol),
        lastClose: lastClose(p, prices, fx),
      })),
  }
}
