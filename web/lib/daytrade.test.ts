import { describe, expect, it } from 'vitest'
import {
  BEFORE_RANGE,
  MARKET_CLOSED,
  costLine,
  etClock,
  flatBy,
  fmtR,
  historyLine,
  isFresh,
  isLive,
  oddsLine,
  orderSignals,
  outcomeLine,
  shares,
  sharesLine,
  statusLine,
  trackRecord,
  whyNotTop3,
  type DayRow,
  type Signal,
} from './daytrade'

// 2026-11-10 is a Tuesday; New York is on EST (UTC-5).
const at = (hhmm: string, day = '2026-11-10') => new Date(`${day}T${hhmm}:00-05:00`).toISOString()

const dayRow = (over: Partial<DayRow> = {}): DayRow => ({
  day: '2026-11-10',
  status: 'scanning',
  cycles: 3,
  lastUpdate: at('10:35'),
  scanned: 5000,
  usable: 4200,
  candidates: 40,
  error: null,
  ...over,
})

const signal = (over: Partial<Signal> = {}): Signal => ({
  id: 1,
  day: '2026-11-10',
  symbol: 'TGTX',
  market: 'US',
  name: 'TG Therapeutics',
  triggerAt: at('10:10'),
  entry: 67.65,
  orHigh: 67.5,
  orLow: 64.6,
  stop: 66.05,
  target: 70.85,
  volumeX: 2.1,
  costPct: 3.1,
  costR: 1.31,
  replay: { replays: 10000, target_first: 0.341, stop_first: 0.52, neither: 0.139, green: 0.48, avg_r: 0.4, sessions: 55 },
  history: { sessions: 55, fired: 37, target: 5, stop: 20, neither: 12, avg_r: -0.12 },
  netReplayR: 0.2,
  netHistoryR: 0.3,
  eligible: true,
  rank: 1,
  headlines: [],
  status: 'open',
  lastPrice: null,
  lastAt: null,
  exitAt: null,
  exitPrice: null,
  grossR: null,
  netR: null,
  ...over,
})

describe('shares', () => {
  it('converts the CAD max loss to USD for a US stock', () => {
    // C$50 at 1.40 = US$35.71; risk US$1.60 a share → 22 shares, risking 22 × 1.60 × 1.40 = C$49.28
    const s = shares(50, 1.6, 'US', 1.4)
    expect(s?.shares).toBe(22)
    expect(s?.riskCad).toBeCloseTo(49.28, 6)
  })

  it('uses the max loss as is for a TSX stock', () => {
    expect(shares(50, 0.7, 'TSX', null)).toEqual({ shares: 71, riskCad: expect.closeTo(49.7, 6) })
    // 0.7 / 0.1 is 6.999… in floating point: still 7 shares
    expect(shares(0.7, 0.1, 'TSX', null)?.shares).toBe(7)
  })

  it('is null when even one share risks more than the max loss', () => {
    expect(shares(50, 60, 'TSX', null)).toBeNull()
    expect(shares(50, 40, 'US', 1.4)).toBeNull() // US$40 × 1.40 = C$56
  })

  it('is null for a US stock without a USD/CAD rate, or a risk that is not positive', () => {
    expect(shares(50, 1, 'US', null)).toBeNull()
    expect(shares(50, 0, 'TSX', null)).toBeNull()
  })

  it('reads as a line, or says why there are none', () => {
    expect(sharesLine(50, 1.6, 'US', 1.4)).toBe('≈ 22 shares (risking ≈ C$49 at the stop)')
    expect(sharesLine(50, 1, 'TSX', null)).toBe('≈ 50 shares (risking ≈ C$50 at the stop)')
    expect(sharesLine(50, 60, 'TSX', null)).toBe('Even one share risks more than your C$50 limit.')
    expect(sharesLine(50, 1, 'US', null)).toBe('No USD/CAD rate yet.')
    expect(sharesLine(50, 30, 'TSX', null)).toBe('≈ 1 share (risking ≈ C$30 at the stop)')
  })
})

describe('isFresh', () => {
  it('is fresh up to 10 minutes after the trigger bar closes', () => {
    expect(isFresh(at('10:10'), at('10:10'))).toBe(true)
    expect(isFresh(at('10:10'), at('10:20'))).toBe(true)
    expect(isFresh(at('10:10'), new Date(Date.parse(at('10:20')) + 1000).toISOString())).toBe(false)
  })
})

describe('etClock', () => {
  it("shows New York's clock with AM/PM", () => {
    expect(etClock(at('10:35'))).toBe('10:35 AM')
    expect(etClock(at('15:55'))).toBe('3:55 PM')
    expect(etClock(at('12:05'))).toBe('12:05 PM')
    expect(etClock('2026-07-01T13:30:00Z')).toBe('9:30 AM') // EDT
  })
})

describe('statusLine', () => {
  it('without a row: before 9:50 on a weekday, closed on a weekend, else no scan yet', () => {
    expect(statusLine(null, at('09:49'))).toBe(BEFORE_RANGE)
    expect(BEFORE_RANGE).toBe('Before 9:50 AM: the opening range is still forming.')
    expect(statusLine(null, at('11:00', '2026-11-14'))).toBe(MARKET_CLOSED) // Saturday
    expect(MARKET_CLOSED).toBe('Market closed today.')
    expect(statusLine(null, at('11:00'))).toBe('No scan has run yet today.')
  })

  it('a closed day, and a waiting one', () => {
    expect(statusLine(dayRow({ status: 'closed', lastUpdate: null }), at('11:00'))).toBe(MARKET_CLOSED)
    expect(statusLine(dayRow({ status: 'waiting', lastUpdate: null }), at('09:40'))).toBe(BEFORE_RANGE)
    expect(statusLine(dayRow({ status: 'waiting', lastUpdate: null }), at('09:52'))).toBe('Waiting for the first scan.')
  })

  it('scanning shows the last update and the next bar', () => {
    expect(statusLine(dayRow({ lastUpdate: new Date(Date.parse(at('10:35')) + 45_000).toISOString() }), at('10:37'))).toBe(
      'Scanning · last update 10:35 AM ET · next ~10:40',
    )
    // no next cycle after the 3:55 bar
    expect(statusLine(dayRow({ lastUpdate: at('15:55') }), at('15:56'))).toBe('Scanning · last update 3:55 PM ET')
  })

  it('a failed day gives the reason and the last good update', () => {
    expect(statusLine(dayRow({ status: 'failed', error: 'Yahoo gave no data this cycle' }), at('10:41'))).toBe(
      "Today's scan failed: Yahoo gave no data this cycle · last update 10:35 AM ET",
    )
    expect(statusLine(dayRow({ status: 'failed', error: 'boom', lastUpdate: null }), at('10:41'))).toBe(
      "Today's scan failed: boom · no update yet today",
    )
  })

  it('a finished day', () => {
    expect(statusLine(dayRow({ status: 'done', lastUpdate: at('15:59') }), at('17:00'))).toBe('Done for today · last update 3:59 PM ET')
  })
})

describe('isLive', () => {
  it('refreshes while waiting or scanning, and after a failed cycle during the session', () => {
    expect(isLive(dayRow({ status: 'waiting' }), at('09:40'))).toBe(true)
    expect(isLive(dayRow(), at('11:00'))).toBe(true)
    expect(isLive(dayRow({ status: 'failed' }), at('11:00'))).toBe(true)
    expect(isLive(dayRow({ status: 'failed' }), at('16:30'))).toBe(false)
    expect(isLive(dayRow({ status: 'done' }), at('16:30'))).toBe(false)
    expect(isLive(null, at('11:00'))).toBe(false)
  })
})

describe('formatters', () => {
  it('R with a sign and a real minus', () => {
    expect(fmtR(0.534)).toBe('+0.53R')
    expect(fmtR(-0.12)).toBe('−0.12R')
    expect(fmtR(0.001)).toBe('0.00R')
  })

  it('flat-by is 3:55 PM, 12:55 PM on a 1:00 PM close', () => {
    expect(flatBy('2026-11-10', 'US')).toBe('3:55 PM')
    expect(flatBy('2026-11-27', 'US')).toBe('12:55 PM')
    expect(flatBy('2026-11-27', 'TSX')).toBe('3:55 PM')
    expect(flatBy('2026-12-24', 'TSX')).toBe('12:55 PM')
  })

  it('history, cost and odds lines', () => {
    expect(historyLine('TGTX', signal().history)).toBe(
      "This rule on TGTX's last 55 sessions: fired 37 times, 5 target, 20 stop; average −0.12R before costs",
    )
    expect(historyLine('TGTX', { skipped: 'only 4 full past session(s); need at least 20' })).toBe(
      'No history: only 4 full past session(s); need at least 20',
    )
    expect(costLine(3.1, 0.534)).toBe('Cost 3.10% round trip = 0.53R')
    expect(oddsLine(signal().replay)).toBe('10,000 replays: target first 34% · stop first 52% · neither 14% · green at close 48%')
    expect(oddsLine({ skipped: 'no bars left to replay after the entry' })).toBe('No replay: no bars left to replay after the entry')
  })

  it('the live outcome', () => {
    expect(outcomeLine(signal())).toBe('Open: no price since the signal yet')
    expect(outcomeLine(signal({ lastPrice: 68.1, lastAt: at('10:35') }))).toBe('Open · last US$68.10 at 10:35 AM')
    expect(outcomeLine(signal({ status: 'target', exitAt: at('10:50'), exitPrice: 70.85, netR: 0.69 }))).toBe(
      'Target hit at 10:50 AM (US$70.85) · +0.69R after costs',
    )
    expect(outcomeLine(signal({ status: 'stop', exitAt: at('10:20'), exitPrice: 66.05, netR: -2.31 }))).toBe(
      'Stopped out at 10:20 AM (US$66.05) · −2.31R after costs',
    )
    expect(outcomeLine(signal({ status: 'flat', exitAt: at('15:55'), exitPrice: 68, netR: -1.09 }))).toBe(
      'Flat at close 3:55 PM (US$68.00) · −1.09R after costs',
    )
  })
})

describe('signals', () => {
  it('orders the top 3 first, then eligible, then by net history R', () => {
    const list = [
      signal({ id: 1, rank: null, eligible: false, netHistoryR: null }),
      signal({ id: 2, rank: 2 }),
      signal({ id: 3, rank: null, eligible: false, netHistoryR: -0.1 }),
      signal({ id: 4, rank: 1 }),
      signal({ id: 5, rank: null, eligible: true, netHistoryR: 0.05 }),
    ]
    expect(orderSignals(list).map((s) => s.id)).toEqual([4, 2, 5, 3, 1])
  })

  it('says why a signal is not in the top 3', () => {
    expect(whyNotTop3(signal({ rank: 2 }))).toBe('Top 3 (#2)')
    expect(whyNotTop3(signal({ rank: null }))).toBe('Ranked below the top 3')
    expect(whyNotTop3(signal({ rank: null, eligible: false, history: { skipped: 'only 4 full past session(s); need at least 20' } }))).toBe(
      'Not enough history: only 4 full past session(s); need at least 20',
    )
    expect(
      whyNotTop3(signal({ rank: null, eligible: false, netHistoryR: null, history: { ...(signal().history as object), fired: 12 } as Signal['history'] })),
    ).toBe('Fired only 12 times in its history (needs 20)')
    expect(whyNotTop3(signal({ rank: null, eligible: false, replay: { skipped: 'no bars left' } }))).toBe('No replay: no bars left')
    expect(whyNotTop3(signal({ rank: null, eligible: false, netHistoryR: -0.2 }))).toBe('History is −0.20R after costs')
    expect(whyNotTop3(signal({ rank: null, eligible: false, netReplayR: -0.05 }))).toBe('Replays are −0.05R after costs')
  })
})

describe('trackRecord', () => {
  const days = Array.from({ length: 25 }, (_, i) => `2026-10-${String(31 - i).padStart(2, '0')}`) // newest first
  const rows = [
    { day: days[0], status: 'target' as const, netR: 1.5 },
    { day: days[0], status: 'stop' as const, netR: -1.2 },
    { day: days[5], status: 'flat' as const, netR: 0.3 },
    { day: days[22], status: 'stop' as const, netR: -1.1 },
  ]

  it('sums the top-3 outcomes of the last 20 and 60 finished days', () => {
    const t = trackRecord(rows, days)
    expect(t.last20).toEqual({ days: 20, count: 3, target: 1, stop: 1, flat: 1, avgNetR: expect.closeTo(0.2, 9), sumNetR: expect.closeTo(0.6, 9) })
    expect(t.last60).toEqual({ days: 25, count: 4, target: 1, stop: 2, flat: 1, avgNetR: expect.closeTo(-0.125, 9), sumNetR: expect.closeTo(-0.5, 9) })
  })

  it('is empty without finished signals', () => {
    expect(trackRecord([], []).last60).toEqual({ days: 0, count: 0, target: 0, stop: 0, flat: 0, avgNetR: null, sumNetR: 0 })
  })
})
