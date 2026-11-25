import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RunnersRecord } from './RunnersRecord'
import type { Runner } from '@/lib/runners'

/** A closed runner signalled on 2026-11-13 under rule `ruleVersion`. */
const closed = (ruleVersion: number, status: Runner['status'], netR: number | null): Runner => ({
  id: 1,
  signalDay: '2026-11-13',
  symbol: 'AKAN',
  name: 'Akanda Corp.',
  ruleVersion,
  changePct: 102.38,
  volumeX: 77.2,
  dollarVolume: 121_326_960,
  closePos: 0.651,
  signalClose: 1.36,
  signalLow: 0.66,
  spreadPct: 2,
  costR: 0.08,
  warnings: [],
  warningsChecked: true,
  status,
  skipReason: null,
  entryDay: '2026-11-16',
  entry: 1.92,
  stop: 1.44,
  target: 2.88,
  holdBy: '2026-11-30',
  lastDay: '2026-11-18',
  lastClose: 2.5,
  exitDay: '2026-11-18',
  exitPrice: 2.88,
  grossR: netR,
  netR,
})

describe('RunnersRecord', () => {
  it('counts only the live rule version and says how many earlier ones it left out', () => {
    const rows = [closed(1, 'target', 1.9), closed(0, 'stop', -1.1), closed(0, 'target', 1.9), closed(0, 'skipped', null)]
    const text = renderToStaticMarkup(<RunnersRecord closed={rows} version={1} today="2026-11-24" />)
    expect(text).toContain('rule version 1')
    // one trade of version 1: +1.90R, not the three of both versions
    expect(text).toMatch(/Last 20 sessions<\/td><td class="r num">\+1\.90R<\/td><td class="r num">1<\/td>/)
    expect(text).toContain('2 finished runners under earlier rule versions are not counted.')
    expect(renderToStaticMarkup(<RunnersRecord closed={rows.slice(0, 1)} version={1} today="2026-11-24" />)).not.toContain('earlier rule versions')
  })

  it('says one finished runner in the singular', () => {
    const text = renderToStaticMarkup(<RunnersRecord closed={[closed(0, 'stop', -1.1)]} version={1} today="2026-11-24" />)
    expect(text).toContain('1 finished runner under earlier rule versions is not counted.')
    expect(text).toContain('No finished runners yet.')
  })
})
