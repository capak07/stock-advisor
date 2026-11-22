import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PicksStatus } from './PicksStatus'
import type { MarketPicks, PickView } from '@/lib/data/picks'
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

const market = (m: 'US' | 'TSX', swing: number, position = 0): MarketPicks => ({
  market: m,
  enabled: true,
  reason: null,
  swing: Array.from({ length: swing }, () => ({}) as PickView),
  position: Array.from({ length: position }, () => ({}) as PickView),
  exitedEarly: [],
  graded: { swing: 0, position: 0 },
})

const LINE = 'US 52.7% vs SPY · TSX 55.1% vs XIU.TO'

describe('PicksStatus', () => {
  it('says there is no run yet instead of a best-chance line (Review Focus 2)', () => {
    const html = renderToStaticMarkup(<PicksStatus run={null} markets={[]} bestChance={null} />)
    expect(html).toContain('No run yet')
    expect(html).not.toContain('needs')
  })

  it('with no picks: None today, the best chance against the 58% bar, and the links', () => {
    const html = renderToStaticMarkup(<PicksStatus run={RUN} markets={[market('US', 0), market('TSX', 0)]} bestChance={LINE} />)
    expect(html).toContain('None today')
    expect(html).toContain(LINE)
    expect(html).toContain('needs 58%')
    expect(html).toContain('Nothing has enough evidence to buy')
    expect(html).toContain('Why none?')
    expect(html).toContain('href="/picks"')
    expect(html).toContain('Watchlist verdicts')
    expect(html).toContain('href="/watchlist"')
  })

  it('with picks: the count per market and no best-chance line', () => {
    const html = renderToStaticMarkup(<PicksStatus run={RUN} markets={[market('US', 2, 1), market('TSX', 1)]} bestChance={LINE} />)
    expect(html).toContain('US')
    expect(html).toContain('3 picks')
    expect(html).toContain('TSX')
    expect(html).toContain('1 pick')
    expect(html).not.toContain(LINE)
    expect(html).not.toContain('None today')
  })

  it('counts no picks for a market whose model failed its check, as the Picks page does', () => {
    const failed = (m: 'US' | 'TSX', n: number): MarketPicks => ({ ...market(m, n), enabled: false, reason: 'only 12 backtest picks (needs 30)' })
    // both markets withheld: None today and the best chance, not "3 picks / Open"
    const none = renderToStaticMarkup(<PicksStatus run={RUN} markets={[failed('US', 3), market('TSX', 0)]} bestChance={LINE} />)
    expect(none).toContain('None today')
    expect(none).toContain(LINE)
    expect(none).not.toContain('3 picks')
    expect(none).not.toContain('Open')
    // one market withheld: the other's count, and None for the withheld one
    const one = renderToStaticMarkup(<PicksStatus run={RUN} markets={[failed('US', 3), market('TSX', 2)]} bestChance={LINE} />)
    expect(one).toContain('2 picks')
    expect(one).not.toContain('3 picks')
    expect(one.replace(/<[^>]+>/g, '')).toContain('USNone')
  })
})
