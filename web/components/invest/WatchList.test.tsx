import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { WatchGroup, WatchLine } from '@/lib/invest/watch'
import { WatchList } from './WatchList'

const line = (over: Partial<WatchLine>): WatchLine => ({
  symbol: 'AAA',
  name: 'Aaa Inc.',
  market: 'US',
  horizonDays: 5,
  pBeat: 0.558,
  q10: -0.031,
  q50: 0.012,
  q90: 0.054,
  benchmark: 'SPY',
  coversCosts: true,
  passes: false,
  ...over,
})
const text = (groups: WatchGroup[]) =>
  renderToStaticMarkup(<WatchList groups={groups} runDay="Nov 23" />)
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .replaceAll('&quot;', '"')
    .replaceAll('&#x27;', "'")

describe('WatchList', () => {
  it('lists each hold with its stocks, chance, middle and range, and whether costs are covered', () => {
    const shown = text([
      { label: '~1 week', lines: [line({})] },
      { label: '~1 month', lines: [line({ symbol: 'BBB', name: null, market: 'TSX', horizonDays: 20, pBeat: 0.51, q50: -0.001, coversCosts: false })] },
    ])
    expect(shown).toContain('Watch list, not picks run of Nov 23')
    expect(shown).toContain('None passes the 58% bar.')
    expect(shown).toContain('Hold ~1 week')
    expect(shown).toContain('AAA Aaa Inc. · US 55.8% +1.2% (−3.1% to +5.4%) covers costs')
    expect(shown).toContain('Hold ~1 month')
    expect(shown).toContain('BBB TSX 51% −0.1% (−3.1% to +5.4%) below costs')
    expect(shown).not.toContain('passes the bar')
  })

  it('marks a stock that meets the picks’ rule', () => {
    const shown = text([{ label: '~1 week', lines: [line({ pBeat: 0.6, passes: true })] }])
    expect(shown).toContain('AAA passes the bar')
    expect(shown).toContain('Only those marked "passes the bar" meet the picks\' rule')
  })

  it('shows nothing without stocks', () => {
    expect(renderToStaticMarkup(<WatchList groups={[]} runDay="Nov 23" />)).toBe('')
  })
})
