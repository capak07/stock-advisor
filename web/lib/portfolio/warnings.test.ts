import { describe, expect, it } from 'vitest'
import type { Sale, Trade } from './types'
import { superficialLossWarnings, tfsaWarnings } from './warnings'

const TODAY = '2026-10-16'
const sale = (over: Partial<Sale>): Sale => ({
  account: 'tfsa',
  symbol: 'RY.TO',
  assetType: 'stock',
  day: '2026-09-01',
  qty: 1,
  proceedsCad: 100,
  costCad: 90,
  gainCad: 10,
  heldDays: 60,
  ...over,
})
const GUIDE = { roundTrips: 24, shortHoldShare: 0.5 }

describe('tfsaWarnings', () => {
  it('stays quiet below 75% of the round-trip guideline', () => {
    expect(tfsaWarnings(Array.from({ length: 17 }, () => sale({})), GUIDE, TODAY)).toEqual([])
  })

  it('warns at 18 of 24 round trips in the last 12 months', () => {
    const sales = [...Array.from({ length: 18 }, () => sale({})), sale({ day: '2025-10-16' })]
    expect(tfsaWarnings(sales, GUIDE, TODAY)).toEqual([
      {
        title: 'TFSA: 18 round trips in 12 months',
        detail: 'Your guideline is 24. Frequent TFSA trading can make gains taxable as business income.',
      },
    ])
  })

  it('warns when most of at least four holds lasted under 30 days', () => {
    const sales = [sale({ heldDays: 3 }), sale({ heldDays: 12 }), sale({ heldDays: 29 }), sale({ heldDays: 30 })]
    expect(tfsaWarnings(sales, GUIDE, TODAY).map((w) => w.title)).toEqual(['TFSA: 3 of 4 holds under 30 days'])
    expect(tfsaWarnings(sales.slice(0, 3), GUIDE, TODAY)).toEqual([])
  })

  it('ignores sells in other accounts', () => {
    expect(tfsaWarnings(Array.from({ length: 30 }, () => sale({ account: 'rrsp' })), GUIDE, TODAY)).toEqual([])
  })
})

describe('superficialLossWarnings', () => {
  const coin = { account: 'crypto' as const, symbol: 'ETH', assetType: 'crypto' as const }
  const loss = sale({ ...coin, day: '2026-10-03', gainCad: -540 })
  const trade = (over: Partial<Trade>): Trade => ({
    side: 'buy', ...coin, qty: 1, price: 4000, currency: 'CAD', fxRateCad: null, day: '2026-06-01', ...over,
  })

  it('names the window after a loss in a taxable account', () => {
    const trades = [trade({}), trade({ side: 'sell', day: '2026-10-03' })]
    expect(superficialLossWarnings([loss], trades, TODAY)).toEqual([
      {
        symbol: 'ETH',
        title: 'ETH: superficial-loss window',
        detail: 'You sold ETH at a loss on Oct 3, 2026. Buying it back before Nov 2, 2026 denies that loss.',
        note: 'Loss window to Nov 2',
      },
    ])
  })

  it('says the loss is likely denied after a buy in the window that is still held', () => {
    const trades = [trade({}), trade({ side: 'sell', day: '2026-10-03' }), trade({ day: '2026-10-10' })]
    expect(superficialLossWarnings([loss], trades, TODAY)[0]).toMatchObject({
      title: 'ETH: the loss is likely superficial',
      note: 'Loss likely denied',
    })
  })

  it('treats a buy days before the sale as the position itself when nothing is left', () => {
    const trades = [trade({ day: '2026-09-25' }), trade({ side: 'sell', day: '2026-10-03' })]
    const sold = sale({ ...coin, day: '2026-10-03', gainCad: -100 })
    expect(superficialLossWarnings([sold], trades, TODAY)[0].title).toBe('ETH: superficial-loss window')
  })

  it('skips gains, sheltered accounts and sales older than 30 days', () => {
    expect(
      superficialLossWarnings(
        [sale({ ...coin, day: '2026-10-03', gainCad: 5 }), sale({ day: '2026-10-03', gainCad: -50 }), sale({ ...coin, day: '2026-09-15', gainCad: -50 })],
        [],
        TODAY,
      ),
    ).toEqual([])
  })
})
