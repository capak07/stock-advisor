import { fmtMoney } from '../format'
import { tradeCurrency } from '../symbols'
import { buildLedger, positionKey } from './ledger'
import type { FxRate, FxRates, PriceBook } from './lookup'
import { PERIODS, growth, periodReturns, type Period, type PeriodReturns } from './returns'
import { ACCOUNT_LABELS, assetKey } from './types'
import type { Account, AssetType, Close, Currency, Market, Trade } from './types'
import { breakdown, taxableEstimate, totals, valueHoldings, type Slice, type Totals } from './valuation'
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
  /** The latest stored close, or null when none is stored. */
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
  sellable: SellOption[]
}

export interface PortfolioInputs {
  trades: Trade[]
  prices: PriceBook
  fx: FxRates
  names: Map<string, string>
  guideline: TfsaGuideline
}

/** Everything the portfolio page shows before the model exists (spec §7.4, §7.5, §9). */
export function portfolioView({ trades, prices, fx, names, guideline }: PortfolioInputs, today: string): PortfolioView {
  const ledger = buildLedger(trades, fx)
  const valued = valueHoldings(ledger.positions, prices, fx).sort((a, b) => b.valueCad - a.valueCad)
  const lossWarnings = superficialLossWarnings(ledger.sales, trades, today)
  const warnings: Warning[] = [
    ...ledger.problems.map((problem) => ({ title: 'A trade was left out', detail: problem })),
    ...tfsaWarnings(ledger.sales, guideline, today),
    ...lossWarnings,
  ]

  const holdings = valued.map((h): HoldingRow => {
    const notes: Note[] = []
    if (h.priceCad === null) notes.push({ text: 'No close yet; at cost', warn: true })
    for (const w of lossWarnings) if (w.symbol === h.symbol && w.note) notes.push({ text: w.note, warn: true })
    const taxable = taxableEstimate(h)
    if (taxable !== null) notes.push({ text: `Taxable: est. ${fmtMoney(taxable, { signed: true })}`, warn: false })
    return {
      key: positionKey(h),
      account: h.account,
      symbol: h.symbol,
      name: names.get(h.symbol) ?? null,
      market: h.market,
      valueCad: h.valueCad,
      gainCad: h.gainCad,
      gainPct: h.gainPct,
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
        lastClose: prices.latest(assetKey(p.assetType, p.symbol)),
      })),
  }
}
