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
const html = (trades: Trade[]) =>
  renderToStaticMarkup(<ResultsCard results={stockResults(trades, PRICES, FX)} />)
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .replaceAll('&gt;', '>')

describe('ResultsCard', () => {
  it('shows a holding with its profit now and a sold stock with what it made, then the totals', () => {
    const text = html([
      trade({}),
      trade({ symbol: 'NVDA', price: 100 }),
      trade({ symbol: 'NVDA', side: 'sell', price: 90, day: '2026-09-20' }),
    ])
    expect(text).toContain('Results by stock 2')
    expect(text).toContain('AAPL Holding 10 @ US$200.00 avg · now US$220.00 TFSA · since Sep 1 +C$280 +10.0% now')
    expect(text).toContain('NVDA Sold 10 · bought @ US$100.00 avg → sold @ US$90.00 avg TFSA · Sep 1 – Sep 20 · held 19 days −C$140 −10.0% sold')
    expect(text).toContain('Made on sales: −C$140 · Open now: +C$280')
  })

  it('shows nothing without trades', () => {
    expect(renderToStaticMarkup(<ResultsCard results={stockResults([], PRICES, FX)} />)).toBe('')
  })
})
