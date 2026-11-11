import { describe, expect, it } from 'vitest'
import {
  BEFORE_RANGE,
  MARKET_CLOSED,
  NO_SIGNALS,
  TRACK_LABEL,
  costHurdleLine,
  costLine,
  etClock,
  fmtR,
  historyLine,
  isFresh,
  isLive,
  noTradeLine,
  oddsLine,
  orderSignals,
  outcomeLine,
  recordEmptyLine,
  shares,
  sharesLine,
  skillEmptyLine,
  skillSignals,
  statusLine,
  strengthLine,
  strengthPct,
  trackRecord,
  whyNotTop3,
  type DayRow,
  type RecordRow,
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
  flatBy: at('15:55'),
  volumeX: 2.1,
  costPct: 3.1,
  costR: 1.31,
  replay: { replays: 10000, target_first: 0.341, stop_first: 0.52, neither: 0.139, green: 0.48, avg_r: 0.4, sessions: 55 },
  history: { sessions: 55, fired: 37, target: 5, stop: 20, neither: 12, avg_r: -0.12 },
  netReplayR: 0.2,
  netHistoryR: 0.3,
  eligible: true,
  rank: 1,
  bestRank: 1,
  skillRank: null,
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
  it('refreshes while waiting or scanning, and after a failed cycle, until 4:05 PM', () => {
    expect(isLive(dayRow({ status: 'waiting' }), at('09:40'))).toBe(true)
    expect(isLive(dayRow(), at('11:00'))).toBe(true)
    expect(isLive(dayRow({ status: 'failed' }), at('11:00'))).toBe(true)
    expect(isLive(dayRow({ status: 'failed' }), at('16:04'))).toBe(true)
    expect(isLive(dayRow({ status: 'failed' }), at('16:05'))).toBe(false)
    expect(isLive(dayRow(), at('16:05'))).toBe(false) // a job that died leaves the day scanning
    expect(isLive(dayRow({ status: 'done' }), at('15:00'))).toBe(false)
    expect(isLive(dayRow({ status: 'closed' }), at('11:00'))).toBe(false)
  })

  it('without a row: refreshes on a weekday from 9:30 AM to 4:05 PM, waiting for the job', () => {
    expect(isLive(null, at('09:29'))).toBe(false)
    expect(isLive(null, at('09:30'))).toBe(true)
    expect(isLive(null, at('16:04'))).toBe(true)
    expect(isLive(null, at('16:05'))).toBe(false)
    expect(isLive(null, at('11:00', '2026-11-14'))).toBe(false) // Saturday
  })
})

describe('formatters', () => {
  it('R with a sign and a real minus', () => {
    expect(fmtR(0.534)).toBe('+0.53R')
    expect(fmtR(-0.12)).toBe('−0.12R')
    expect(fmtR(0.001)).toBe('0.00R')
  })

  it('the no-trade line, and none checked yet', () => {
    expect(noTradeLine(4)).toBe('No signal today has a positive record after costs (4 signals checked).')
    expect(noTradeLine(0)).toBe('No signals yet today.')
    expect(NO_SIGNALS).toBe('No signals yet today.')
  })

  it("the breakout's strength above the opening-range high", () => {
    expect(strengthPct(signal({ entry: 68.12, orHigh: 67.5 }))).toBeCloseTo(0.9185, 4)
    expect(strengthLine(signal({ entry: 68.12, orHigh: 67.5 }))).toBe('+0.92% above the range high')
    // the trigger tests the raw close; entry is stored to the cent, so it can sit at or under the stored high
    expect(strengthLine(signal({ entry: 50, orHigh: 50 }))).toBe('Just above the range high')
    expect(strengthLine(signal({ entry: 50.001, orHigh: 50 }))).toBe('Just above the range high') // +0.002% rounds to 0.00
    expect(strengthLine(signal({ entry: 4.2, orHigh: 4.2041 }))).toBe('Just above the range high')
    expect(strengthLine(signal({ entry: 50.005, orHigh: 50 }))).toBe('+0.01% above the range high')
  })

  it('the round-trip cost the trade must beat, for a US stock only', () => {
    expect(costHurdleLine(signal({ costR: 1.314 }))).toBe(
      'Your round-trip cost (currency conversion both ways plus the spread) is 1.31R: the trade must gain more than that to pay.',
    )
    expect(costHurdleLine(signal({ market: 'TSX', costR: 0.05 }))).toBeNull()
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
    expect(outcomeLine(signal({ status: 'target', exitAt: at('10:50'), exitPrice: 70.85, grossR: 2, netR: 0.64 }))).toBe(
      'Target hit at 10:50 AM (US$70.85) · +2.00R before costs, +0.64R after',
    )
    expect(outcomeLine(signal({ status: 'stop', exitAt: at('10:20'), exitPrice: 66.05, grossR: -1, netR: -2.31 }))).toBe(
      'Stopped out at 10:20 AM (US$66.05) · −1.00R before costs, −2.31R after',
    )
    expect(outcomeLine(signal({ status: 'flat', exitAt: at('15:55'), exitPrice: 68, grossR: 0.22, netR: -1.09 }))).toBe(
      'Flat at close 3:55 PM (US$68.00) · +0.22R before costs, −1.09R after',
    )
  })

  it('a finished outcome with only one of its R values says that one', () => {
    expect(outcomeLine(signal({ status: 'target', exitAt: at('10:50'), exitPrice: 70.85, netR: 0.69 }))).toBe(
      'Target hit at 10:50 AM (US$70.85) · +0.69R after costs',
    )
    expect(outcomeLine(signal({ status: 'stop', grossR: -1 }))).toBe('Stopped out · −1.00R before costs')
    expect(outcomeLine(signal({ status: 'flat' }))).toBe('Flat at close')
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

  it("picks the skill's top 3 in rank order, whatever their after-costs place", () => {
    const list = [
      signal({ id: 1, skillRank: 3, rank: null, eligible: false }),
      signal({ id: 2, skillRank: null, rank: 1 }),
      signal({ id: 3, skillRank: 1, rank: null }),
      signal({ id: 4, skillRank: 2, rank: 2 }), // in both lists
    ]
    expect(skillSignals(list).map((s) => s.id)).toEqual([3, 4, 1])
    expect(skillSignals([signal({ skillRank: null })])).toEqual([])
  })

  it('treats a signal without the skill rank field (migration 0014 not applied yet) as unranked', () => {
    const { skillRank: _gone, ...old } = signal({ id: 9, skillRank: 1 })
    void _gone
    expect(skillSignals([old as Signal, signal({ id: 2, skillRank: 1 })]).map((s) => s.id)).toEqual([2])
  })

  it("says why the skill's list is empty: no signals yet, or none ranked yet", () => {
    expect(skillEmptyLine(0)).toBe('No signals yet today.')
    expect(skillEmptyLine(3)).toBe("The skill's ranking is not set yet.")
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
  // in the after-costs top 3 (best rank) only, unless a skill rank is given
  const row = (day: string, status: RecordRow['status'], grossR: number | null, netR: number | null, over: Partial<RecordRow> = {}): RecordRow => ({
    day,
    status,
    grossR,
    netR,
    skillRank: null,
    bestRank: 1,
    ...over,
  })
  const rows = [
    row(days[0], 'target', 2, 1.5),
    row(days[0], 'stop', -1, -1.2),
    row(days[5], 'flat', 0.4, 0.3),
    row(days[22], 'stop', -1, -1.1),
  ]
  const EMPTY = { count: 0, target: 0, stop: 0, flat: 0, avgGrossR: null, avgNetR: null, sumNetR: 0 }

  it('sums the after-costs top 3 of the last 20 and 60 finished days, before and after costs', () => {
    // an open row on a finished day (never finalized) counts nowhere
    const t = trackRecord([...rows, row(days[1], 'open', null, null)], days)
    expect(t.costs.last20).toEqual({
      days: 20,
      count: 3,
      target: 1,
      stop: 1,
      flat: 1,
      avgGrossR: expect.closeTo(0.4666667, 6),
      avgNetR: expect.closeTo(0.2, 9),
      sumNetR: expect.closeTo(0.6, 9),
    })
    expect(t.costs.last60).toEqual({
      days: 25,
      count: 4,
      target: 1,
      stop: 2,
      flat: 1,
      avgGrossR: expect.closeTo(0.1, 9),
      avgNetR: expect.closeTo(-0.125, 9),
      sumNetR: expect.closeTo(-0.5, 9),
    })
  })

  it("counts each list by its own rank: a signal in both lists counts in both, a list with nothing finished is empty", () => {
    const t = trackRecord(
      [
        row(days[0], 'target', 2, 0.64, { skillRank: 1, bestRank: null }),
        row(days[0], 'stop', -1, -1.36, { skillRank: 2, bestRank: null }),
        row(days[1], 'target', 2, 1.9, { skillRank: 1, bestRank: 1 }), // in both lists
        row(days[2], 'open', null, null, { skillRank: 3, bestRank: null }),
      ],
      days,
    )
    expect(t.skill.last20).toEqual({
      days: 20,
      count: 3,
      target: 2,
      stop: 1,
      flat: 0,
      avgGrossR: expect.closeTo(1, 9),
      avgNetR: expect.closeTo(0.3933333, 6),
      sumNetR: expect.closeTo(1.18, 9),
    })
    expect(t.costs.last20).toEqual({ days: 20, count: 1, target: 1, stop: 0, flat: 0, avgGrossR: 2, avgNetR: 1.9, sumNetR: 1.9 })

    const onlySkill = trackRecord([row(days[0], 'flat', 0.1, -0.2, { skillRank: 1, bestRank: null })], days)
    expect(onlySkill.costs.last20).toEqual({ days: 20, ...EMPTY })
    expect(onlySkill.costs.last60).toEqual({ days: 25, ...EMPTY })
    expect(onlySkill.skill.last60.count).toBe(1)
  })

  it('is empty without finished days', () => {
    const t = trackRecord([], [])
    expect(t.skill.last60).toEqual({ days: 0, ...EMPTY })
    expect(t.costs.last20).toEqual({ days: 0, ...EMPTY })
  })

  it('leaves a row without the skill rank field out of the skill list', () => {
    const { skillRank: _gone, ...old } = row(days[0], 'target', 2, 1.5)
    void _gone
    const t = trackRecord([old as RecordRow], days)
    expect(t.skill.last20.count).toBe(0)
    expect(t.costs.last20.count).toBe(1)
  })

  it('says so only before the first finished day', () => {
    expect(recordEmptyLine(trackRecord([], []).skill.last60)).toBe('No finished day-trade signals yet.')
    expect(recordEmptyLine(trackRecord([], days.slice(0, 3)).skill.last60)).toBeNull() // dash rows instead
    expect(recordEmptyLine(trackRecord(rows, days).costs.last60)).toBeNull()
  })

  it('labels the record as paper, for each list', () => {
    expect(TRACK_LABEL).toBe("Paper: what each list's trades would have done.")
  })
})
