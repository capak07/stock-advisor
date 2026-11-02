import { describe, expect, it } from 'vitest'
import type { PickView } from './data/picks'
import { btcGuide, holdingGuides, joinPlans, pickGuide, verdictGuide } from './guidance'
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
  ...over,
})

const kinds = (plan: { steps: { kind: string }[] } | null) => plan?.steps.map((s) => s.kind)

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
