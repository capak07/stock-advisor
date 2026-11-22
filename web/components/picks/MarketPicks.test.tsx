import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PicksEmpty } from './MarketPicks'
import type { MarketPicks } from '@/lib/data/picks'
import type { Run } from '@/lib/runs'

const RUN: Run = {
  id: 7,
  kind: 'pre_close',
  et_date: '2026-11-20',
  started_at: '2026-11-20T20:00:00Z',
  finished_at: '2026-11-20T20:15:00Z',
  status: 'success',
  published: true,
  sources_ok: 30,
  sources_total: 33,
  summary: {},
}

const market = (m: 'US' | 'TSX', enabled: boolean, reason: string | null = null): MarketPicks => ({
  market: m,
  enabled,
  reason,
  swing: [],
  position: [],
  exitedEarly: [],
  graded: { swing: 0, position: 0 },
})

const CHANCES = [
  { benchmark: 'XIU.TO', pBeat: 0.551 },
  { benchmark: 'SPY', pBeat: 0.527 },
] as const
const text = (html: string) => html.replace(/<[^>]+>/g, '').replace(/&#x27;/g, "'").replace(/&amp;/g, '&')

describe('PicksEmpty', () => {
  it("a run with no picks: the run's best chance against the 58% bar, and why", () => {
    const html = renderToStaticMarkup(
      <PicksEmpty run={RUN} chances={[...CHANCES]} markets={[market('US', true), market('TSX', false, 'only 12 backtest picks (needs 30)')]} />,
    )
    const t = text(html)
    expect(t).toContain('No picks today')
    expect(t).toContain('US 52.7% vs SPY · TSX 55.1% vs XIU.TO')
    expect(t).toContain('needs 58%')
    expect(t).toContain('Nothing has enough evidence to buy')
    expect(t).toContain('a pick needs a chance of at least 58%')
    // the three tiles: the best chance of the run, the bar, the backtest it also needs
    expect(t).toContain('Best chance today55.1%')
    expect(t).toContain('A pick needs58%')
    expect(t).toContain('And a backtest of30 picks')
    // each market's own reason
    expect(t).toContain('Nothing cleared the bar this run')
    expect(t).toContain('only 12 backtest picks (needs 30)')
    expect(html).toContain('href="/watchlist"')
    expect(html).toContain('href="#picks-why"')
    expect(t).not.toContain('No run yet')
  })

  it('a run without forecasts still says nothing has enough evidence, without a best-chance line', () => {
    const t = text(renderToStaticMarkup(<PicksEmpty run={RUN} chances={[]} markets={[market('US', true), market('TSX', true)]} />))
    expect(t).toContain('No picks today')
    expect(t).toContain('Nothing has enough evidence to buy')
    expect(t).not.toContain('The best chance of beating the market was')
  })

  it('with no run yet: says so instead of a best-chance line (Review Focus 2)', () => {
    const t = text(renderToStaticMarkup(<PicksEmpty run={null} chances={[]} markets={[]} />))
    expect(t).toContain('No run yet')
    expect(t).not.toContain('No picks today')
    expect(t).not.toContain('best chance')
    expect(t).not.toContain('needs 58%')
  })
})
