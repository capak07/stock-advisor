import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PortfolioSummary } from './PortfolioSummary'
import type { Period, PeriodReturns } from '@/lib/portfolio/returns'

const days = (n: number) => Array.from({ length: n }, (_, i) => `2026-08-${String((i % 28) + 1).padStart(2, '0')}`)
const series = (n: number, end: number) => Array.from({ length: n }, (_, i) => (end * i) / (n - 1))

/** Returns for every period: the portfolio ends at `end`%, SPY at `spy`%; the 1D period ends on Aug 2. */
const periods = (end: number, spy: number, n = 64): Record<Period, PeriodReturns> => {
  const r = (len: number) => ({ days: days(len), portfolio: series(len, end), xiu: null, spy: series(len, spy) })
  return { '1d': r(2), '1w': r(6), '1m': r(22), '3m': r(n), '12m': r(n), all: r(n) }
}

const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

describe('PortfolioSummary', () => {
  it('shows C$0.00 and No holdings yet without a chart for an empty portfolio (Review Focus 1)', () => {
    const html = renderToStaticMarkup(
      <PortfolioSummary totals={{ valueCad: 0, costCad: 0, gainCad: 0, unpriced: [] }} periods={null} accounts={[]} holdings={0} today="2026-08-02" />,
    )
    expect(html).toContain('C$0.00')
    expect(html).not.toContain('data-price') // no day move to flash
    expect(html).toContain('No holdings yet')
    expect(html).not.toContain('<svg')
    expect(html).toContain('href="/portfolio"')
  })

  it("shows only today's money made, its percent and the accounts: no total, all time, SPY gap, chart or cash", () => {
    // 1,108 now after +10.8% today: 108 made
    const html = renderToStaticMarkup(
      <PortfolioSummary
        totals={{ valueCad: 1108, costCad: 900, gainCad: 208, unpriced: [] }}
        periods={periods(10.8, 8.7)}
        accounts={['TFSA', 'Non-registered']}
        holdings={3}
        today="2026-08-02"
      />,
    )
    expect(html).toMatch(/data-testid="today-value" data-price="up"[^>]*>\+C\$108\.00</) // flashes after a Refresh
    expect(text(html)).toContain('+10.8% today')
    expect(text(html)).toContain('Today · TFSA and Non-registered')
    expect(html).not.toContain('1,108')
    expect(html).not.toContain('All time')
    expect(html).not.toContain('SPY')
    expect(html).not.toContain('<svg')
    expect(html).not.toMatch(/cash/i)
  })

  it('shows a loss in the loss colour', () => {
    // 900 now after −10% today: 100 lost
    const html = renderToStaticMarkup(
      <PortfolioSummary totals={{ valueCad: 900, costCad: 950, gainCad: -50, unpriced: [] }} periods={periods(-10, 2)} accounts={['TFSA']} holdings={1} today="2026-08-02" />,
    )
    expect(html).toMatch(/class="big num loss" data-testid="today-value" data-price="down"[^>]*>−C\$100\.00</)
    expect(text(html)).toContain('−10.0% today')
  })

  it("names the last session's weekday when it isn't today (a weekend, a holiday or before a Refresh), and says today when it is", () => {
    // the 1D period ends on Friday, Nov 20
    const p = periods(10.8, 8.7)
    p['1d'] = { ...p['1d'], days: ['2026-11-19', '2026-11-20'] }
    const props = { totals: { valueCad: 1108, costCad: 900, gainCad: 208, unpriced: [] }, periods: p, accounts: ['TFSA'], holdings: 3 }
    const sunday = text(renderToStaticMarkup(<PortfolioSummary {...props} today="2026-11-22" />))
    expect(sunday).toContain('+10.8% on Fri')
    expect(sunday).not.toContain('% today')
    const friday = text(renderToStaticMarkup(<PortfolioSummary {...props} today="2026-11-20" />))
    expect(friday).toContain('+10.8% today')
  })

  it('says so when the holdings have no prices to compare yet', () => {
    const html = renderToStaticMarkup(
      <PortfolioSummary totals={{ valueCad: 500, costCad: 500, gainCad: 0, unpriced: [] }} periods={null} accounts={['TFSA']} holdings={1} today="2026-08-02" />,
    )
    expect(html).toMatch(/data-testid="today-value"[^>]*>—</)
    expect(html).toContain('No prices to compare yet')
    expect(html).not.toContain('data-price')
  })
})
