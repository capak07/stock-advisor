import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { TickerForecast } from '@/lib/data/ticker'
import type { Verdict } from '@/lib/verdicts'
import { ForecastProvider } from './ForecastCard'
import { OutlookCard, PhoneOutlook } from './OutlookCard'

const forecast = (over: Partial<TickerForecast> = {}): TickerForecast => ({
  benchmark: 'SPY',
  span: 'trading days',
  horizons: [
    { horizon: 5, q10: -0.03, q50: 0.002, q90: 0.034, pBeat: 0.506 },
    { horizon: 21, q10: -0.09, q50: 0.005, q90: 0.104, pBeat: 0.52 },
    { horizon: 63, q10: -0.16, q50: 0.019, q90: 0.222, pBeat: 0.53 },
  ],
  advice: null,
  pastPicks: [],
  ...over,
})

const text = (html: string) => html.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'")

const render = (
  f: TickerForecast | null,
  { verdict = null, judgedAt = null, start = 21, coin = false }: { verdict?: Verdict | null; judgedAt?: number | null; start?: number; coin?: boolean } = {},
) =>
  renderToStaticMarkup(
    <ForecastProvider forecast={f} initialHorizon={start}>
      <PhoneOutlook verdict={verdict} coin={coin} />
      <OutlookCard verdict={verdict} judgedAt={judgedAt} price={364.18} currency="USD" coin={coin} emptyText="No forecast yet." />
    </ForecastProvider>,
  )

describe('OutlookCard', () => {
  it('reads a Hold or no verdict as no clear edge in words, with the chance as a number', () => {
    for (const verdict of ['hold', null] as const) {
      const out = text(render(forecast(), { verdict }))
      expect(out).toContain('No clear edge')
      expect(out).toContain('52%chance to beat the market over 21 trading days')
      expect(out).toContain('A coin flip is 50%. Picks need 58%.')
      expect(out).toContain('Likely range at 21 trading days')
      expect(out).not.toMatch(/[▲▼↑↓]/) // no big arrows
    }
  })

  it('names a Buy or an Avoid, at the selected horizon', () => {
    expect(text(render(forecast(), { verdict: 'buy', judgedAt: 21 }))).toContain('Buy')
    const avoid = text(render(forecast(), { verdict: 'avoid', judgedAt: 63, start: 63 }))
    expect(avoid).toContain('Avoid')
    expect(avoid).toContain('53%chance to beat the market over 63 trading days')
    expect(avoid).not.toContain('The verdict is for')
  })

  it('says which horizon the verdict is for when another is shown', () => {
    expect(text(render(forecast(), { verdict: 'avoid', judgedAt: 63, start: 21 }))).toContain('The verdict is for 63 trading days.')
  })

  it('shows the likely range as prices from the last price, with each percent', () => {
    const out = text(render(forecast()))
    expect(out).toContain('Low (q10)US$331.40−9.0%')
    expect(out).toContain('MedianUS$366.00+0.5%')
    expect(out).toContain('High (q90)US$402.05+10.4%')
    expect(out).toContain('The circle is the last price, US$364.18. If SPY is flat')
  })

  it('lists only the forecast horizons in the control, the selected one first chosen', () => {
    const html = render(forecast({ horizons: forecast().horizons.slice(1) }), { start: 63 })
    expect(html).toContain('aria-label="Forecast horizon in trading days"')
    expect(html.match(/role="tab"/g)).toHaveLength(2)
    expect(html).toMatch(/aria-selected="true"[^>]*>63d</)
  })

  it('compares a coin with its benchmark and leaves out the picks bar', () => {
    const out = text(render(forecast({ benchmark: 'BTC', span: 'days' }), { coin: true }))
    expect(out).toContain('52%chance to beat BTC over 21 days')
    expect(out).toContain('A coin flip is 50%.')
    expect(out).not.toContain('Picks need')
  })

  it('puts the outlook in one line for a phone', () => {
    expect(text(render(forecast(), { verdict: 'hold' }))).toContain('Outlook (21 trading days): no clear edge. 52% chance to beat the market.')
  })

  it('says when a forecast appears, or that this run had none', () => {
    const none = text(render(null))
    expect(none).toContain('No forecast yet.')
    expect(none).not.toContain('chance to beat')
    expect(text(render(forecast({ horizons: [] })))).toContain('No forecast this run. Its earlier picks are under Past picks.')
  })
})
