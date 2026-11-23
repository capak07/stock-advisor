import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { FxRates, PriceBook } from '@/lib/portfolio/lookup'
import { stockResults } from '@/lib/portfolio/results'
import type { Trade } from '@/lib/portfolio/types'
import { ResultsCard } from './ResultsCard'

const FX = new FxRates([{ day: '2026-09-01', usdCad: 1.4 }])
const PRICES = new PriceBook(new Map([['stock:AAPL', [{ day: '2026-10-16', close: 220, currency: 'USD' as const }]]]))
const trade = (over: Partial<Trade>): Trade => ({
  side: 'buy',
  account: 'tfsa',
  symbol: 'AAPL',
  assetType: 'stock',
  qty: 10,
  price: 200,
  currency: 'USD',
  fxRateCad: 1.4,
  day: '2026-09-01',
  ...over,
})
const html = (trades: Trade[], taxPct: number | null = null) =>
  renderToStaticMarkup(<ResultsCard results={stockResults(trades, PRICES, FX)} taxPct={taxPct} />)
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .replaceAll('&gt;', '>')
    .replaceAll('&#x27;', "'")

describe('ResultsCard', () => {
  it('shows each stock on two lines, what it made and what is left after tax, then the totals', () => {
    const text = html([
      trade({}),
      trade({ symbol: 'NVDA', price: 100 }),
      trade({ symbol: 'NVDA', side: 'sell', price: 90, day: '2026-09-20' }),
    ])
    expect(text).toContain('Results by stock 2')
    expect(text).toContain('AAPL Holding 10 @ US$200.00 avg · now US$220.00 TFSA · since Sep 1 +C$280 +10.0% now +C$280 +10.0% after tax')
    expect(text).toContain(
      'NVDA Sold 10 · bought @ US$100.00 avg → sold @ US$90.00 avg TFSA · Sep 1 – Sep 20 · held 19 days −C$140 −10.0% made −C$140 −10.0% after tax',
    )
    expect(text).toContain('Made on sales: −C$140 · after tax −C$140')
    expect(text).toContain('Open now: +C$280 · after tax +C$280')
    expect(text).toContain("A TFSA, RRSP or FHSA isn't taxed.")
  })

  it('taxes half of a non-registered gain at the rate set in Settings', () => {
    const text = html([trade({ account: 'non_registered' })], 40)
    expect(text).toContain('+C$280 +10.0% now +C$224 +8.0% after tax')
    expect(text).toContain('Open now: +C$280 · after tax +C$224')
    expect(text).toContain('half of a gain in a non-registered or crypto account is taxed at your 40% rate')
  })

  it('asks for the tax rate when a taxable account has results and none is set', () => {
    const markup = renderToStaticMarkup(<ResultsCard results={stockResults([trade({ account: 'non_registered' })], PRICES, FX)} taxPct={null} />)
    expect(markup).toContain('href="/settings"')
    const text = html([trade({ account: 'non_registered' })])
    expect(text).toContain('+C$280 +10.0% now — after tax')
    expect(text).toContain('Open now: +C$280 · after tax —')
    expect(text).toContain('Set your marginal tax rate in Settings')
  })

  it('shows nothing without trades', () => {
    expect(renderToStaticMarkup(<ResultsCard results={stockResults([], PRICES, FX)} taxPct={null} />)).toBe('')
  })
})
