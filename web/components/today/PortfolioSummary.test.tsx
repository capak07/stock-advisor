import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PortfolioSummary } from './PortfolioSummary'
import type { Period, PeriodReturns } from '@/lib/portfolio/returns'

const days = (n: number) => Array.from({ length: n }, (_, i) => `2026-08-${String((i % 28) + 1).padStart(2, '0')}`)
const series = (n: number, end: number) => Array.from({ length: n }, (_, i) => (end * i) / (n - 1))

/** Returns for every period: the portfolio ends at `end`%, SPY at `spy`%. */
const periods = (end: number, spy: number, n = 64): Record<Period, PeriodReturns> => {
  const r = (len: number) => ({ days: days(len), portfolio: series(len, end), xiu: null, spy: series(len, spy) })
  return { '1d': r(2), '1w': r(6), '1m': r(22), '3m': r(n), '12m': r(n), all: r(n) }
}

describe('PortfolioSummary', () => {
  it('shows C$0.00 and No holdings yet without a chart for an empty portfolio (Review Focus 1)', () => {
    const html = renderToStaticMarkup(
      <PortfolioSummary totals={{ valueCad: 0, costCad: 0, gainCad: 0, unpriced: [] }} periods={null} accounts={[]} holdings={0} />,
    )
    expect(html).toContain('C$0.00')
    expect(html).toContain('No holdings yet')
    expect(html).not.toContain('<svg')
    expect(html).toContain('href="/portfolio"')
  })

  it('shows the value, today, all time, the gap to SPY and a sparkline, and no cash figure', () => {
    const html = renderToStaticMarkup(
      <PortfolioSummary
        totals={{ valueCad: 12340.18, costCad: 11000, gainCad: 1340.18, unpriced: [] }}
        periods={periods(10.8, 8.7)}
        accounts={['TFSA', 'Non-registered']}
        holdings={3}
      />,
    )
    expect(html).toContain('C$12,340.18')
    expect(html).toContain('today')
    expect(html).toContain('All time')
    expect(html).toContain('+10.8%')
    expect(html).toContain('+2.1 pts')
    expect(html).toContain('TFSA and Non-registered')
    expect(html).toContain('class="spark draw"')
    expect(html).toContain('class="line"')
    expect(html).not.toMatch(/cash/i)
  })

  it('names the comparison since the first buy when there is less than a year of history', () => {
    const html = renderToStaticMarkup(
      <PortfolioSummary totals={{ valueCad: 100, costCad: 90, gainCad: 10, unpriced: [] }} periods={periods(1, 2)} accounts={['TFSA']} holdings={1} />,
    )
    expect(html).toContain('vs SPY, since first buy')
    expect(html).toContain('−1.0 pts')
  })
})
