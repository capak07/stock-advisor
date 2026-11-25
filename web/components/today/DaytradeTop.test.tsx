import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { DaytradeTop } from './DaytradeTop'
import { BEFORE_RANGE, type DayRow, type Signal } from '@/lib/daytrade'

// Monday, Nov 23 2026 (EST, UTC−5)
const MON_9AM = '2026-11-23T14:00:00Z'
const MON_11AM = '2026-11-23T16:00:00Z'
const SAT_10AM = '2026-11-21T15:00:00Z'

const row = (status: DayRow['status'], lastUpdate: string | null = null): DayRow => ({
  day: '2026-11-23',
  status,
  cycles: 3,
  lastUpdate,
  scanned: 5000,
  usable: 4000,
  candidates: 40,
  error: null,
})

const REPLAY = { replays: 10000, target_first: 0.34, stop_first: 0.52, neither: 0.14, green: 0.48, avg_r: 0.4, sessions: 55 }
const HISTORY = { sessions: 55, fired: 37, target: 5, stop: 20, neither: 12, avg_r: 1.6 }

const signal = (symbol: string, rank: number): Signal =>
  ({
    id: rank,
    day: '2026-11-23',
    symbol,
    market: 'US',
    name: null,
    triggerAt: '2026-11-23T15:15:00Z',
    entry: 100,
    orHigh: 99.9,
    orLow: 98,
    stop: 99,
    target: 102,
    flatBy: '2026-11-23T20:55:00Z',
    volumeX: 2,
    costPct: 3,
    costR: 0.5,
    replay: REPLAY,
    history: HISTORY,
    netReplayR: 0.2,
    netHistoryR: 0.12,
    eligible: true,
    rank,
    bestRank: rank,
    skillRank: null,
    headlines: [],
    status: 'target',
    lastPrice: null,
    lastAt: null,
    exitAt: null,
    exitPrice: null,
    grossR: null,
    netR: null,
  }) as Signal

const render = (day: DayRow | null, now: string, top: Signal[] = [], signals = 0) =>
  renderToStaticMarkup(<DaytradeTop day={day} top={top} signals={signals} now={now} />)

describe('DaytradeTop', () => {
  it('says No session today on a weekend without a row (Review Focus 3)', () => {
    expect(render(null, SAT_10AM)).toContain('No session today')
  })

  it('says No session today for a stored closed row (a holiday)', () => {
    expect(render(row('closed'), MON_11AM)).toContain('No session today')
  })

  it("shows the Day trade page's status line on a weekday before the morning job writes the row", () => {
    const early = render(null, MON_9AM)
    expect(early).toContain(BEFORE_RANGE)
    expect(early).not.toContain('No session today')
    const late = render(null, MON_11AM)
    expect(late).toContain('No scan has run yet today.')
    expect(late).not.toContain('No session today')
  })

  it('a day that ran with no top 3 shows its status line and why nothing made it', () => {
    const html = render(row('done', '2026-11-23T20:55:00Z'), '2026-11-23T22:00:00Z', [], 5)
    expect(html).toContain('Done for today · last update 3:55 PM ET')
    expect(html).toContain('No signal today has a positive record after costs (5 signals checked).')
  })

  it('shows the top 3, the first with its entry, target and stop', () => {
    const html = render(row('scanning', '2026-11-23T16:00:00Z'), MON_11AM, [signal('TSLA', 1), signal('AMD', 2)], 4)
    expect(html.match(/data-testid="today-trade"/g)).toHaveLength(2)
    // the currency in the label, the figure whole: "Entry US$" over "100.00"
    expect(html.match(/>Entry US\$</g)).toHaveLength(1)
    expect(html).toContain('<b>100.00</b>')
    expect(html).toContain('<b class="gain">102.00</b>')
    expect(html).toContain('<b class="loss">99.00</b>')
    expect(html).toContain('>Target US$<')
    expect(html).toContain('>Stop US$<')
    // how far each level is from the entry
    expect(html).toContain('<span class="lvl-pct num gain">+2.0%</span>')
    expect(html).toContain('<span class="lvl-pct num loss">−1.0%</span>')
    expect(html).toContain('Target hit')
    expect(html).toContain('10,000 replays: target first 34%')
    expect(html).toContain('history +0.12R after costs')
  })

  it("uses the Day trade page's status chips: Fresh or Late while open, then how it ended", () => {
    const fresh = { ...signal('TSLA', 1), status: 'open' as const, triggerAt: '2026-11-23T15:58:00Z' } // 2 minutes before 11:00
    const late = { ...signal('AMD', 2), status: 'open' as const, triggerAt: '2026-11-23T15:15:00Z' }
    const stopped = { ...signal('SOFI', 3), status: 'stop' as const }
    const html = render(row('scanning', MON_11AM), MON_11AM, [fresh, late, stopped], 3)
    expect(html).toContain('<span class="chip triggered">Fresh</span>')
    expect(html).toContain('<span class="chip waiting">Late</span>')
    expect(html).toContain('<span class="chip stopped">Stopped out</span>')
  })
})
