import { describe, expect, it } from 'vitest'
import { covers, fmtLatency, fmtSize, sentimentNotice, sourceRows, tally, type Health, type Source } from './sources'

const source = (name: string, extra: Partial<Source> = {}): Source => ({
  name,
  category: 'prices',
  core: false,
  cadence: 'per_run',
  assetTypes: ['stock'],
  markets: ['US', 'TSX'],
  ...extra,
})
const health = (name: string, status: Health['status'], extra: Partial<Health> = {}): Health => ({
  source: name,
  status,
  latencyMs: 100,
  records: 10,
  error: null,
  failures: 0,
  attemptedAt: '2026-10-16T19:10:00Z',
  ...extra,
})

describe('coverage', () => {
  const finra = source('finra_short_volume', { markets: ['US'] })
  const coins = source('coingecko', { assetTypes: ['crypto'], markets: [] })

  it('matches a stock by its market and a coin by its asset type', () => {
    expect(covers(finra, { assetType: 'stock', market: 'US' })).toBe(true)
    expect(covers(finra, { assetType: 'stock', market: 'TSX' })).toBe(false)
    expect(covers(coins, { assetType: 'crypto', market: null })).toBe(true)
    expect(covers(coins, { assetType: 'stock', market: 'US' })).toBe(false)
  })
})

describe('sourceRows', () => {
  const sources = [
    source('yfinance_bars', { core: true }),
    source('sec_form4', { category: 'fundamentals', markets: ['US'] }),
    source('fred', { category: 'macro', core: true }),
    source('new_feed', { category: 'news' }),
  ]
  const run = [
    health('yfinance_bars', 'ok'),
    health('sec_form4', 'partial', { error: 'PartialFetch: stopped after 41 of 300 symbols' }),
    health('fred', 'ok'),
    health('gone', 'failed'), // no longer in the registry
  ]
  const checks = [
    health('fred', 'failed', { attemptedAt: '2026-10-16T19:09:00Z', failures: 3 }),
    health('fred', 'ok', { attemptedAt: '2026-10-15T19:09:00Z' }),
    health('yfinance_bars', 'ok', { attemptedAt: '2026-10-16T19:09:00Z' }),
  ]
  const rows = sourceRows(sources, run, checks, new Map([['fred', '2026-10-16T19:10:00Z']]))

  it('lists every registered source, problems first, then core sources, then by name', () => {
    expect(rows.map((r) => r.name)).toEqual(['fred', 'new_feed', 'sec_form4', 'yfinance_bars'])
    expect(rows.map((r) => r.problem)).toEqual([true, true, true, false])
  })

  it("joins each source's run result, its newest daily check and its last good answer", () => {
    const fred = rows[0]
    expect(fred.run?.status).toBe('ok')
    expect(fred.check).toMatchObject({ status: 'failed', failures: 3 }) // the newest check, not the older ok
    expect(fred.lastOk).toBe('2026-10-16T19:10:00Z')
    expect(rows[1]).toMatchObject({ name: 'new_feed', run: null, check: null, lastOk: null }) // not run yet
  })

  it('counts a run or a check by status', () => {
    expect(tally(rows, (r) => r.run)).toEqual({ total: 4, ok: 2, partial: 1, stale: 0, failed: 0, skipped: 0, missing: 1 })
    expect(tally(rows, (r) => r.check)).toMatchObject({ total: 4, ok: 1, failed: 1, missing: 2 })
  })
})

describe('sentimentNotice', () => {
  it("says why a run's headlines went unscored, and nothing when FinBERT scored them", () => {
    const news = (sentiment: string) => ({ news: { items: 40, sentiment } })
    expect(sentimentNotice(news('finbert'))).toBeNull()
    expect(sentimentNotice({})).toBeNull() // a run from before Plan 2f
    expect(sentimentNotice(news('unavailable'))).toMatch(/^FinBERT couldn't be loaded/)
    expect(sentimentNotice(news('skipped: run budget'))).toMatch(/^The run ran out of time/)
    expect(sentimentNotice(news('failed: OSError: no space left'))).toBe(
      "Scoring headlines failed (OSError: no space left), so this run's headlines have no sentiment.",
    )
    expect(sentimentNotice(news('no items'))).toBe('No news source returned a headline in this run.')
  })
})

describe('formats', () => {
  it('writes latency the way the mockup does', () => {
    expect([fmtLatency(0), fmtLatency(262), fmtLatency(1356), fmtLatency(430383)]).toEqual([
      'from cache',
      '262 ms',
      '1.4 s',
      '7 min 10 s',
    ])
  })

  it('writes database sizes in MB, or GB past 1,000 MB', () => {
    expect([fmtSize(14_200_000), fmtSize(3_400_000), fmtSize(1_250_000_000)]).toEqual(['14 MB', '3.4 MB', '1.25 GB'])
  })
})
