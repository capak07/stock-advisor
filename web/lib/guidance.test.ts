import { describe, expect, it } from 'vitest'
import type { PickView } from './data/picks'
import { btcGuide, holdingGuides, investGuide, joinPlans, pickGuide, verdictGuide } from './guidance'
import { CANCEL_SELL_AT_NOTE, SELL_AT_NOTE } from './orders'
import type { StockLine } from './invest/allocate'
import type { HoldingAction } from './portfolio/actions'

const NOW = new Date('2026-10-28T15:00:00Z') // 11:00 in Toronto, a Wednesday
const ctx = { now: NOW, usdCad: 1.4 }

const pick = (over: Partial<PickView> = {}): PickView => ({
  id: 1,
  symbol: 'RY.TO',
  name: null,
  sector: null,
  market: 'TSX',
  style: 'position',
  rank: 1,
  horizon: 63,
  q10: null,
  q50: null,
  q90: null,
  pBeat: null,
  exitBy: '2027-01-19',
  entry: 100,
  stop: 95,
  riskLevel: 'medium',
  maxPositionPct: 3,
  topFactors: [],
  catalysts: [],
  cost: null,
  basis: null,
  benchmark: 'XIU.TO',
  atrPct: 0.02,
  dollarVolume20: 5e6,
  chosenBy: 'p',
  scoreRank: null,
  scoreOf: null,
  trackRecord: null,
  ...over,
})

const action = (over: Partial<HoldingAction>): HoldingAction => ({
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  action: 'hold',
  review: false,
  reasons: [],
  warnings: [],
  trailingStop: null,
  q10: null,
  q50: null,
  q90: null,
  horizonDays: null,
  exitBy: null,
  riskLevel: null,
  refPrice: null,
  atrPct: null,
  dollarVolume20: null,
  previousStop: null,
  maxPositionPct: null,
  exitPlan: null,
  ...over,
})

const kinds = (plan: { steps: { kind: string }[] } | null) => plan?.steps.map((s) => s.kind)

/** A passed exit plan with a sell-at price, for a TSX holding at C$150. */
const PLAN: NonNullable<HoldingAction['exitPlan']> = {
  assetType: 'stock',
  status: 'pass',
  basis: 'forecast',
  horizon: 21,
  recheckBy: '2026-11-27',
  low: 140,
  mid: 152,
  high: 165,
  sellAt: 160,
  pTouch: 0.33,
  pStopFirst: null,
  pUp: 0.55,
  breakeven: null,
  pBreakeven: null,
  drift: 0.009,
  costPrice: 120,
}

describe('pickGuide', () => {
  it('buys the max size in whole shares, the rest at market, then the stop', () => {
    const g = pickGuide(pick(), 50_000, ctx)!
    expect(g.caption).toBeNull()
    expect(kinds(g.plan)).toEqual(['limit', 'market', 'stop-limit', 'bracket'])
    expect(g.plan.steps[0]).toMatchObject({ qty: 14, price: 100.5 }) // C$1,500 at a 0.5% buffer
    expect(g.plan.steps[1]).toMatchObject({ amountCad: 93 })
    expect(g.plan.steps[2]).toMatchObject({ qty: 14, stop: 95, limit: 94.05 })
  })

  it('offers the same buy as one bracket order, its take-profit at the top of the range', () => {
    const steps = pickGuide(pick({ q90: 0.1 }), 50_000, ctx)!.plan.steps
    expect(steps.at(-1)).toMatchObject({ kind: 'bracket', qty: 14, price: 100.5, takeProfit: 110, stop: 95 })
    expect(pickGuide(pick(), 50_000, ctx)!.plan.steps.at(-1)).toMatchObject({ kind: 'bracket', takeProfit: null, stop: 95 })
  })

  it('sizes an empty portfolio at C$1,000 and says so', () => {
    const g = pickGuide(pick(), null, ctx)!
    expect(g.caption).toBe('for C$1,000')
    expect(g.plan.steps[0]).toMatchObject({ qty: 9 })
  })

  it('gives a US pick nothing without a USD/CAD rate', () => {
    expect(pickGuide(pick({ symbol: 'AAPL', market: 'US' }), 50_000, { now: NOW, usdCad: null })).toBeNull()
  })
})

describe('verdictGuide', () => {
  const buy = {
    verdict: 'buy' as const,
    reasons: [],
    details: { entry_ref_price: 100, stop: 95, max_position_pct: 3, exit_by: '2026-11-10' },
    atrPct: 0.02,
    dollarVolume20: null,
    q90: 0.08,
  }

  it("plans a Buy like a pick from its details, and nothing for a Hold or a Buy missing its price", () => {
    expect(kinds(verdictGuide('RY.TO', buy, 50_000, ctx)!.plan)).toEqual(['limit', 'market', 'stop-limit', 'bracket'])
    expect(verdictGuide('RY.TO', buy, 50_000, ctx)!.plan.steps.at(-1)).toMatchObject({ takeProfit: 108, stop: 95 })
    // without its exit-by a bracket can't say whether it outlasts the hold
    const noExit = { ...buy, details: { entry_ref_price: 100, stop: 95, max_position_pct: 3 } }
    expect(kinds(verdictGuide('RY.TO', noExit, 50_000, ctx)!.plan)).toEqual(['limit', 'market', 'stop-limit'])
    expect(verdictGuide('RY.TO', { ...buy, verdict: 'hold' }, 50_000, ctx)).toBeNull()
    expect(verdictGuide('RY.TO', { ...buy, details: { stop: 95, max_position_pct: 3 } }, 50_000, ctx)).toBeNull()
  })
})

describe('holdingGuides', () => {
  const held = { qty: 5, valueCad: 1000, portfolioCad: 100_000 }

  it('sells a whole position at a limit under the decision price', () => {
    const { order } = holdingGuides(action({ symbol: 'MSFT', action: 'sell', refPrice: 400 }), held, ctx)
    expect(order!.steps).toMatchObject([{ kind: 'limit', side: 'sell', qty: 5, price: 396 }])
  })

  it("adds up to the risk level's max size, with the trailing stop, and skips an Add already at it", () => {
    const add = action({ action: 'add', refPrice: 50, atrPct: 0.02, riskLevel: 'medium', trailingStop: 45 })
    const { order } = holdingGuides(add, held, ctx)
    expect(order!.steps[0]).toMatchObject({ kind: 'limit', side: 'buy', qty: 39 }) // C$3,000 − C$1,000 at C$50.25
    expect(order!.steps.at(-1)).toMatchObject({ kind: 'stop-limit', qty: 39, stop: 45 })
    expect(holdingGuides(add, { ...held, valueCad: 3500 }, ctx).order).toBeNull()
  })

  it('offers an Add as one bracket order on the new shares, the held ones keeping their stop', () => {
    const add = action({ action: 'add', refPrice: 50, atrPct: 0.02, riskLevel: 'medium', trailingStop: 45, q90: 0.12, exitBy: '2026-11-25' })
    const { order } = holdingGuides(add, held, ctx)
    expect(kinds(order)).toEqual(['limit', 'market', 'stop-limit', 'bracket']) // C$40 left over buys a fraction
    // the top of the holding's range on its price, C$50 × 1.12; the trailing stop as its stop loss
    expect(order!.steps.at(-1)).toMatchObject({ kind: 'bracket', qty: 39, price: 50.25, takeProfit: 56, stop: 45 })
    expect(order!.notes).toContain('A bracket covers only the shares this buy adds; the shares you hold keep their own stop-limit.')
  })

  it('gives an Add no bracket without a trailing stop or an exit-by, and none for a coin', () => {
    const base = { action: 'add' as const, refPrice: 50, atrPct: 0.02, riskLevel: 'medium' as const, q90: 0.12 }
    expect(kinds(holdingGuides(action({ ...base, exitBy: '2026-11-25' }), held, ctx).order)).toEqual(['limit', 'market'])
    expect(kinds(holdingGuides(action({ ...base, trailingStop: 45 }), held, ctx).order)).toEqual(['limit', 'market', 'stop-limit'])
    const coin = action({ ...base, symbol: 'ETH', assetType: 'crypto', account: 'crypto', trailingStop: 45, exitBy: '2026-11-25' })
    expect(kinds(holdingGuides(coin, held, ctx).order)).toEqual(['limit'])
  })

  it("sizes an Add by the holding's stored max position, not only its risk level's", () => {
    const add = action({ action: 'add', refPrice: 50, atrPct: 0.02, riskLevel: 'medium', maxPositionPct: 2 })
    expect(holdingGuides(add, held, ctx).order!.steps[0]).toMatchObject({ kind: 'limit', side: 'buy', qty: 19 }) // C$2,000 − C$1,000 at C$50.25
  })

  it("prices a holding's order at its latest price (a Refresh's live one) over the run's decision price", () => {
    const sell = action({ symbol: 'MSFT', action: 'sell', refPrice: 400 })
    const live = { day: '2026-10-28', close: 420, currency: 'USD' as const }
    expect(holdingGuides(sell, { ...held, latest: live }, ctx).order!.steps[0]).toMatchObject({ price: 415.8 }) // 1% under 420
    const coin = action({ symbol: 'ETH', assetType: 'crypto', account: 'crypto', action: 'sell', refPrice: 2000 })
    const cad = { day: '2026-10-28', close: 3000, currency: 'CAD' as const } // a coin's live quote is already CAD
    expect(holdingGuides(coin, { ...held, latest: cad }, ctx).order!.steps[0]).toMatchObject({ price: 2970 })
  })

  it('keeps a stop on the whole position and says when to raise it', () => {
    const { order, stop } = holdingGuides(action({ trailingStop: 146.1, previousStop: 140, refPrice: 150 }), { ...held, qty: 10 }, ctx)
    expect(order).toBeNull()
    expect(stop!.steps[0].text).toMatch(/^Stop-limit sell 10 sh: stop C\$146\.10, .* · raise it from C\$140\.00$/)
  })

  it('offers a limit sell at the exit plan\'s sell-at price only for a holding without a trailing stop', () => {
    const exitPlan = {
      assetType: 'stock' as const,
      status: 'pass' as const,
      basis: 'forecast' as const,
      horizon: 21,
      recheckBy: '2026-11-27',
      low: 140,
      mid: 152,
      high: 165,
      sellAt: 160.004,
      pTouch: 0.33,
      pStopFirst: null,
      pUp: 0.55,
      breakeven: null,
      pBreakeven: null,
      drift: 0.009,
      costPrice: 120,
    }
    const bare = holdingGuides(action({ refPrice: 150, exitPlan }), { ...held, qty: 12.4 }, ctx)
    expect(bare.order).toBeNull()
    expect(bare.stop!.steps).toMatchObject([{ kind: 'limit', side: 'sell', qty: 12, price: 160, expiry: '90 days' }])
    expect(bare.stop!.steps[0].text).toBe('Limit sell 12 sh at C$160.00, expiry 90 days')
    // beside a stop it stays hidden until Wealthsimple is known to hold both orders on the same shares
    const stopped = holdingGuides(action({ refPrice: 150, trailingStop: 140, exitPlan }), { ...held, qty: 12.4 }, ctx)
    expect(kinds(stopped.stop)).toEqual(['stop-limit'])
    // no sell-at price, no order
    expect(holdingGuides(action({ refPrice: 150, exitPlan: { ...exitPlan, sellAt: null } }), held, ctx).stop).toBeNull()
  })

  it('offers the sell-at limit sell only on a held or added position with no stop, never beside a Sell or a Trim (R18)', () => {
    const exitPlan = {
      assetType: 'stock' as const,
      status: 'pass' as const,
      basis: 'forecast' as const,
      horizon: 21,
      recheckBy: '2026-11-27',
      low: 140,
      mid: 152,
      high: 165,
      sellAt: 160,
      pTouch: 0.33,
      pStopFirst: null,
      pUp: 0.55,
      breakeven: null,
      pBreakeven: null,
      drift: 0.009,
      costPrice: 120,
    }
    const qty = 12.4
    const guide = (over: Partial<HoldingAction>) =>
      holdingGuides(action({ refPrice: 150, riskLevel: 'medium', exitPlan, ...over }), { ...held, qty }, ctx)
    const steps = (g: ReturnType<typeof holdingGuides>) => [...(g.order?.steps ?? []), ...(g.stop?.steps ?? [])]
    const mentionsSellAt = (g: ReturnType<typeof holdingGuides>) => steps(g).filter((s) => s.text.includes('C$160.00'))
    const sellAtStep = { kind: 'limit', side: 'sell', qty: 12, price: 160, expiry: '90 days', text: 'Limit sell 12 sh at C$160.00, expiry 90 days' }

    // a Sell: no step in either slot names the sell-at price
    expect(mentionsSellAt(guide({ action: 'sell' }))).toEqual([])
    // a Trim: only the trim order, and its sells never exceed the holding
    const trim = guide({ action: 'trim' })
    expect(mentionsSellAt(trim)).toEqual([])
    expect(trim.stop).toBeNull()
    expect(steps(trim)).toMatchObject([{ kind: 'limit', side: 'sell', qty: 4 }])
    expect(steps(trim).some((s) => s.expiry === '90 days')).toBe(false)
    const sold = steps(trim).filter((s) => s.side === 'sell').reduce((sum, s) => sum + (s.qty ?? 0), 0)
    expect(sold).toBeLessThanOrEqual(qty)
    // a Hold (plain or asked to review) and an Add: the sell-at limit sell
    for (const over of [{ action: 'hold' as const }, { action: 'hold' as const, review: true }, { action: 'add' as const }]) {
      expect(guide(over).stop!.steps).toMatchObject([sellAtStep])
    }
    // with a stop, none of the four has it
    for (const action of ['sell', 'trim', 'hold', 'add'] as const) {
      expect(mentionsSellAt(guide({ action, trailingStop: 140 }))).toEqual([])
    }
  })

  it('offers the sell-at limit sell only for a plan that passed the check, not an unvalidated one (R20b)', () => {
    const passed = holdingGuides(action({ refPrice: 150, exitPlan: PLAN }), { ...held, qty: 12 }, ctx)
    expect(passed.stop!.steps).toMatchObject([{ kind: 'limit', side: 'sell', qty: 12, price: 160, expiry: '90 days' }])
    for (const status of ['unvalidated', 'range_only', 'fail'] as const) {
      const g = holdingGuides(action({ refPrice: 150, exitPlan: { ...PLAN, status } }), { ...held, qty: 12 }, ctx)
      expect(g).toEqual({ order: null, stop: null })
    }
  })

  it("carries the sell-at order's lifecycle note, and on a Sell, a Trim and a stop the note to cancel it first (R20c)", () => {
    const qty = { ...held, qty: 12 }
    const guide = (over: Partial<HoldingAction>) => holdingGuides(action({ refPrice: 150, exitPlan: PLAN, ...over }), qty, ctx)
    expect(guide({}).stop!.notes).toEqual([SELL_AT_NOTE])
    expect(CANCEL_SELL_AT_NOTE).toBe('Cancel any resting limit sell on these shares first.')
    // any status: an earlier run may have offered the order
    for (const status of ['pass', 'unvalidated', 'range_only', 'fail'] as const) {
      const exitPlan = { ...PLAN, status }
      expect(guide({ action: 'sell', exitPlan }).order!.notes).toContain(CANCEL_SELL_AT_NOTE)
      expect(guide({ action: 'trim', exitPlan }).order!.notes).toContain(CANCEL_SELL_AT_NOTE)
      expect(guide({ action: 'hold', exitPlan, trailingStop: 140 }).stop!.notes).toContain(CANCEL_SELL_AT_NOTE)
      expect(guide({ action: 'trim', exitPlan, trailingStop: 140 }).stop!.notes).toContain(CANCEL_SELL_AT_NOTE)
    }
    // without a plan, no note on a Sell, a Trim or a stop
    for (const g of [guide({ action: 'sell', exitPlan: null }), guide({ action: 'trim', exitPlan: null }), guide({ exitPlan: null, trailingStop: 140 })]) {
      expect([...(g.order?.notes ?? []), ...(g.stop?.notes ?? [])]).not.toContain(CANCEL_SELL_AT_NOTE)
    }
    // the sell-at order itself does not say to cancel itself
    expect(guide({}).stop!.notes).not.toContain(CANCEL_SELL_AT_NOTE)
    // a coin is never offered a limit sell, so its orders never mention one
    const coin = action({ symbol: 'ETH', assetType: 'crypto', account: 'crypto', action: 'sell', refPrice: 2000, trailingStop: 1800, exitPlan: { ...PLAN, assetType: 'crypto' } })
    const g = holdingGuides(coin, held, ctx)
    expect([...(g.order?.notes ?? []), ...(g.stop?.notes ?? [])]).not.toContain(CANCEL_SELL_AT_NOTE)
  })

  it("converts a coin's USD prices to CAD, and gives USD holdings nothing without a rate", () => {
    const coin = action({ symbol: 'ETH', assetType: 'crypto', account: 'crypto', trailingStop: 1800, refPrice: 2000 })
    const { stop } = holdingGuides(coin, held, ctx)
    expect(stop!.steps).toMatchObject([{ kind: 'alert' }])
    expect(stop!.steps[0].stop).toBeCloseTo(2520)
    expect(holdingGuides(coin, held, { now: NOW, usdCad: null })).toEqual({ order: null, stop: null })
  })
})

describe('btcGuide and joinPlans', () => {
  it('offers only the recurring buy without a BTC price', () => {
    expect(kinds(btcGuide({ amount: 100, priceCad: null }, ctx))).toEqual(['recurring'])
    expect(kinds(btcGuide({ amount: 100, priceCad: 90_000 }, ctx))).toEqual(['limit', 'recurring'])
  })

  it('keeps each note once', () => {
    const plan = { steps: [], notes: ['a', 'b'] }
    expect(joinPlans(plan, null, { steps: [], notes: ['b'] }).notes).toEqual(['a', 'b'])
  })
})

describe('investGuide', () => {
  const line = (over: Partial<StockLine> = {}): StockLine => ({
    symbol: 'RY.TO',
    name: null,
    assetType: 'stock',
    market: 'TSX',
    sector: null,
    amount: 1000,
    shares: 20,
    qualifies: false,
    cost: 0.003,
    vol60: 0.2,
    volatility: 'low',
    price: 50,
    currency: 'CAD',
    atrPct: 0.02,
    dollarVolume20: 5e6,
    horizonDays: 21,
    q10: -0.02,
    q50: 0.03,
    q90: 0.08,
    pBeat: 0.55,
    benchmark: 'XIU.TO',
    ...over,
  })

  it("buys the line, then offers it as one bracket order with the picks' stop and the top of its range", () => {
    const plan = investGuide(line(), ctx)!
    expect(kinds(plan)).toEqual(['limit', 'market', 'bracket']) // C$45 left over buys a fraction
    // C$1,000 at C$50.25 is 19 sh; a 21-day hold is a position hold: 3 ranges under C$50
    expect(plan.steps[2]).toMatchObject({ qty: 19, price: 50.25, takeProfit: 54, stop: 47 })
    expect(plan.notes).toContain("The bracket's stop loss is the picks' rule: 2× the daily range under the price for a hold up to 20 days, 3× (at most 15% under) for longer.")
  })

  it("follows the market's tuned stop rule", () => {
    const plan = investGuide(line(), ctx, { TSX: { swingAtr: 2, positionAtr: 2 } })!
    expect(plan.steps[2]).toMatchObject({ stop: 48 })
    expect(plan.notes.join(' ')).toContain('2× (at most 15% under) for longer')
  })

  it('offers no bracket without a daily range, and none for a coin', () => {
    expect(kinds(investGuide(line({ atrPct: null }), ctx))).toEqual(['limit', 'market'])
    const coin = line({ symbol: 'ETH', assetType: 'crypto', market: null, currency: 'CAD', price: 3000, atrPct: 0.04, horizonDays: 14 })
    expect(kinds(investGuide(coin, ctx))).toEqual(['limit'])
  })
})
