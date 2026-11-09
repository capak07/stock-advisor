import { describe, expect, it } from 'vitest'
import { buildFeed, type FeedItem } from './monitor'

const item = (kind: FeedItem['kind'], symbol: string, at: string): FeedItem => ({ kind, symbol, at, title: `${kind} ${at}` })
const empty = { news: [], filings: [], insiders: [], earnings: [], alerts: [] }
const opts = { since: '2026-11-01T00:00:00Z', now: '2026-11-09T12:00:00Z' }

describe('buildFeed', () => {
  it('drops items older than since', () => {
    const filings = [item('filing', 'A', '2026-10-30T00:00:00Z'), item('filing', 'A', '2026-11-05T00:00:00Z')]
    expect(buildFeed({ ...empty, filings }, opts).map((f) => f.at)).toEqual(['2026-11-05T00:00:00Z'])
  })

  it('keeps the 3 newest news items per symbol', () => {
    const news = ['02', '03', '04', '05'].map((d) => item('news', 'A', `2026-11-${d}T00:00:00Z`))
    news.push(item('news', 'B', '2026-11-02T00:00:00Z'))
    const feed = buildFeed({ ...empty, news }, opts)
    expect(feed.filter((f) => f.symbol === 'A').map((f) => f.at)).toEqual([
      '2026-11-05T00:00:00Z', '2026-11-04T00:00:00Z', '2026-11-03T00:00:00Z',
    ])
    expect(feed.filter((f) => f.symbol === 'B')).toHaveLength(1)
  })

  it('keeps earnings only within the next 14 days', () => {
    const earnings = [
      item('earnings', 'A', '2026-11-08T00:00:00Z'),
      item('earnings', 'B', '2026-11-12T00:00:00Z'),
      item('earnings', 'C', '2026-11-30T00:00:00Z'),
    ]
    expect(buildFeed({ ...empty, earnings }, opts).map((f) => f.symbol)).toEqual(['B'])
  })

  it('puts upcoming earnings first, soonest first, then the rest newest first', () => {
    const feed = buildFeed({
      news: [item('news', 'A', '2026-11-08T00:00:00Z')],
      filings: [item('filing', 'A', '2026-11-07T00:00:00Z')],
      insiders: [item('insider', 'A', '2026-11-09T00:00:00Z')],
      earnings: [item('earnings', 'B', '2026-11-20T00:00:00Z'), item('earnings', 'C', '2026-11-12T00:00:00Z')],
      alerts: [],
    }, opts)
    expect(feed.map((f) => f.kind + f.symbol)).toEqual(['earningsC', 'earningsB', 'insiderA', 'newsA', 'filingA'])
  })
})
