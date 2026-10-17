import { describe, expect, it } from 'vitest'
import type { Run } from './runs'
import { runLabel, runSources, runWhen, staleNotice } from './runs'

const run = (over: Partial<Run>): Run => ({
  id: 2,
  kind: 'pre_close',
  et_date: '2026-10-16',
  started_at: '2026-10-16T19:15:00Z',
  finished_at: '2026-10-16T19:31:00Z',
  status: 'success',
  published: true,
  sources_ok: 30,
  sources_total: 33,
  summary: {},
  ...over,
})

describe('run labels', () => {
  it("uses Toronto's clock and the run's kind", () => {
    expect(runLabel(run({}))).toBe('Pre-close 15:31')
    expect(runWhen(run({}))).toBe('Oct 16 · pre-close 15:31')
    expect(runWhen(run({ kind: 'early_close', finished_at: null, started_at: '2026-10-16T16:15:00Z' }))).toBe(
      'Oct 16 · early close 12:15',
    )
  })

  it('counts sources once the run has', () => {
    expect(runSources(run({}))).toBe('30/33')
    expect(runSources(run({ sources_ok: null }))).toBeNull()
  })
})

describe('staleNotice', () => {
  const published = run({ id: 1, kind: 'pre_open', finished_at: '2026-10-16T12:24:00Z' })

  it('is quiet when the newest finished run worked', () => {
    expect(staleNotice([run({})], published)).toBeNull()
    expect(staleNotice([run({ status: 'running' }), run({ status: 'degraded' })], published)).toBeNull()
    expect(staleNotice([], null)).toBeNull()
  })

  it("names a failed run's reasons and the results still shown", () => {
    const failed = run({ status: 'failed', published: false, summary: { failed_reason: ['TSX: universe too small (2 < 300)'] } })
    expect(staleNotice([failed, published], published)).toEqual({
      title: 'The Oct 16 · pre-close 15:31 run failed:',
      detail: 'TSX: universe too small (2 < 300). Showing the Oct 16 · pre-open 08:24 results until the next run.',
    })
  })

  it('looks past a run still in progress, and says when nothing has published', () => {
    const failed = run({ status: 'failed', published: false })
    expect(staleNotice([run({ status: 'running' }), failed], null)).toEqual({
      title: 'The Oct 16 · pre-close 15:31 run failed:',
      detail: 'See the run summary. No run has published yet.',
    })
  })
})
