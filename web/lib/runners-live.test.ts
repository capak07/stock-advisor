import { describe, expect, it } from 'vitest'
import type { Runner } from './runners'
import {
  GAPPED,
  STARTING_PLAN,
  UNDER_STOP,
  fetchRunnerQuotes,
  gainText,
  liveRunner,
  liveRunners,
  liveValue,
  parseDaily,
  planFor,
  planRuleOf,
  runnerChartUrl,
  type DayBar,
  type LiveRunner,
  type RunnerQuote,
} from './runners-live'

/** BENF's 2026-11-24 ignition (close 0.915, low 0.579), waiting for the Nov 25 open. */
const runner = (over: Partial<Runner> = {}): Runner => ({
  id: 1,
  signalDay: '2026-11-24',
  symbol: 'BENF',
  name: 'Beneficient',
  ruleVersion: 1,
  changePct: 101,
  volumeX: 31,
  dollarVolume: 346_441_517,
  closePos: 0.64,
  signalClose: 0.915,
  signalLow: 0.579,
  spreadPct: 3.13,
  costR: 0.12,
  warnings: [],
  warningsChecked: true,
  status: 'waiting',
  skipReason: null,
  entryDay: null,
  entry: null,
  stop: 0.68,
  target: 1.39,
  holdBy: '2026-12-09',
  lastDay: null,
  lastClose: null,
  exitDay: null,
  exitPrice: null,
  grossR: null,
  netR: null,
  ...over,
})

const bar = (day: string, open: number, high: number, low: number, close: number): DayBar => ({ day, open, high, low, close })
/** BENF's real Nov 24 and Nov 25 sessions from Yahoo. */
const NOV24 = bar('2026-11-24', 0.654, 1.1, 0.579, 0.915)
const NOV25 = bar('2026-11-25', 0.8376, 0.9876, 0.7532, 0.8998)
const quote = (bars: DayBar[], closed = true, at = '2026-11-25T21:00:00.000Z'): RunnerQuote => ({ bars, at, closed })
const V1 = planRuleOf({ gap_skip: null, target_r: 2.0, stop_floor: 0.25, hold_sessions: 10 })

describe('planRuleOf', () => {
  it('reads a frozen rule and fills a missing key with the starting value', () => {
    expect(V1).toEqual({ gapSkip: null, stopFloor: 0.25, targetR: 2 })
    expect(planRuleOf({ gap_skip: 0.15, target_r: 1.5 })).toEqual({ gapSkip: 0.15, stopFloor: 0.25, targetR: 1.5 })
    expect(planRuleOf({ stop_floor: null })).toEqual({ gapSkip: null, stopFloor: null, targetR: 2 })
    expect(planRuleOf(null)).toEqual(STARTING_PLAN)
  })
})

describe('planFor', () => {
  it("puts the stop at the closer of the signal low and 25% under the entry, as plan.py's plan_for", () => {
    expect(planFor(0.8376, 0.579, V1)).toEqual({ entry: 0.8376, stop: 0.62, target: 1.27 }) // BENF Nov 25
    expect(planFor(1.11, 0.67, V1)).toEqual({ entry: 1.11, stop: 0.83, target: 1.67 }) // GLXG
    expect(planFor(0.8587, 0.73, V1)).toEqual({ entry: 0.8587, stop: 0.73, target: 1.12 }) // LGHL: the low is closer
    expect(planFor(1.92, 1.0, V1)).toEqual({ entry: 1.92, stop: 1.44, target: 2.88 }) // 1.92 * 0.75 floors to 1.44, not 1.43
  })

  it('has no plan without a stop under the entry', () => {
    const lowOnly = { ...V1, stopFloor: null }
    expect(planFor(1, 1.2, lowOnly)).toBeNull()
    expect(planFor(1, 0.9, lowOnly)).toEqual({ entry: 1, stop: 0.9, target: 1.2 })
  })
})

describe('liveRunner: a waiting signal', () => {
  it("is bought at the first open after the signal day and valued at Yahoo's close", () => {
    const live = liveRunner(runner(), quote([NOV24, NOV25]), V1)
    expect(live).toEqual({
      kind: 'open',
      entryDay: '2026-11-25',
      plan: { entry: 0.8376, stop: 0.62, target: 1.27 },
      day: '2026-11-25',
      price: 0.8998,
      closed: true,
      at: '2026-11-25T21:00:00.000Z',
    })
    const value = liveValue(live!)!
    expect(value.text).toBe('Closed US$0.8998 on Nov 25: worth US$89.98')
    expect(gainText(value.paper)).toBe('+US$6.22 (+7.4%)')
    expect(value.r).toBeCloseTo(0.0622 / 0.2176)
  })

  it('shows the price and its time while the session trades', () => {
    const live = liveRunner(runner(), quote([NOV24, { ...NOV25, close: 0.9012 }], false, '2026-11-25T20:42:00.000Z'), V1)!
    expect(liveValue(live)!.text).toBe('Now US$0.9012 at 3:42 PM ET: worth US$90.12')
  })

  it('has nothing to show before the open', () => {
    expect(liveRunner(runner(), quote([NOV24]), V1)).toBeNull()
  })

  it('is skipped when it gaps up past the rule or opens under the stop', () => {
    const gappy = { ...V1, gapSkip: 0.15 }
    expect(liveRunner(runner(), quote([bar('2026-11-25', 1.06, 1.1, 1, 1.05)]), gappy)).toEqual({
      kind: 'skipped',
      entryDay: '2026-11-25',
      entry: 1.06,
      reason: GAPPED,
    })
    expect(liveRunner(runner(), quote([bar('2026-11-25', 1.05, 1.1, 1, 1.05)]), gappy)?.kind).toBe('open') // 14.8% up
    const lowOnly = { ...V1, stopFloor: null }
    expect(liveRunner(runner({ signalLow: 0.6 }), quote([bar('2026-11-25', 0.58, 0.6, 0.5, 0.55)]), lowOnly)).toMatchObject({
      kind: 'skipped',
      reason: UNDER_STOP,
    })
  })

  it('exits at the stop or the target the day it is touched, a stop first when a bar touches both', () => {
    const exit = (b: DayBar) => liveRunner(runner(), quote([NOV24, b]), V1) as Extract<LiveRunner, { kind: 'exited' }>
    const stop = exit(bar('2026-11-25', 0.8376, 0.9, 0.6, 0.7))
    expect(stop).toMatchObject({ kind: 'exited', status: 'stop', price: 0.62, atOpen: false })
    expect(liveValue(stop)!.text).toBe('Hit the stop at US$0.6200 on Nov 25: got back US$62.00')
    expect(gainText(liveValue(stop)!.paper)).toBe('−US$21.76 (−26.0%)')
    expect(liveValue(stop)!.r).toBeCloseTo(-1)
    const target = exit(bar('2026-11-25', 0.8376, 1.3, 0.8, 1.2))
    expect(target).toMatchObject({ status: 'target', price: 1.27 })
    expect(liveValue(target)!.text).toBe('Hit the target at US$1.27 on Nov 25: got back US$127.00')
    expect(liveValue(target)!.r).toBeCloseTo(2, 1)
    expect(exit(bar('2026-11-25', 0.8376, 1.3, 0.6, 1))).toMatchObject({ status: 'stop' })
  })

  it('fills at the open when a later bar opens past the stop or the target', () => {
    const later = liveRunner(runner(), quote([NOV24, NOV25, bar('2026-11-27', 0.5, 0.55, 0.45, 0.5)]), V1)!
    expect(later).toMatchObject({ kind: 'exited', status: 'stop', day: '2026-11-27', price: 0.5, atOpen: true })
    expect(liveValue(later)!.text).toBe('Opened under the stop at US$0.5000 on Nov 27: got back US$50.00')
    const up = liveRunner(runner(), quote([NOV24, NOV25, bar('2026-11-27', 1.4, 1.5, 1.35, 1.45)]), V1)!
    expect(liveValue(up)!.text).toBe('Opened over the target at US$1.40 on Nov 27: got back US$140.00')
  })

  it('sells at the hold-by close once that session is over', () => {
    const held = liveRunner(runner({ holdBy: '2026-11-25' }), quote([NOV24, NOV25]), V1)!
    expect(held).toMatchObject({ kind: 'exited', status: 'held', price: 0.8998 })
    expect(liveValue(held)!.text).toBe('Held to Nov 25: sold at the close, US$0.8998: got back US$89.98')
    expect(liveRunner(runner({ holdBy: '2026-11-25' }), quote([NOV24, NOV25], false), V1)?.kind).toBe('open')
  })
})

describe('liveRunner: an open runner', () => {
  const open = runner({ status: 'open', entryDay: '2026-11-25', entry: 0.8376, stop: 0.62, target: 1.27, lastDay: '2026-11-25', lastClose: 0.8998 })

  it('reads only the bars after its stored close', () => {
    expect(liveRunner(open, quote([NOV24, NOV25]), V1)).toBeNull()
    const live = liveRunner(open, quote([NOV24, NOV25, bar('2026-11-27', 0.9, 0.95, 0.88, 0.93)], false, '2026-11-27T16:10:00.000Z'), V1)!
    expect(live).toMatchObject({ kind: 'open', entryDay: '2026-11-25', day: '2026-11-27', price: 0.93, closed: false })
    expect(liveValue(live)!.text).toBe('Now US$0.9300 at 11:10 AM ET: worth US$93.00')
  })

  it('uses the stored plan, not one from the rule', () => {
    const stored = { ...open, stop: 0.7, target: 1.1 }
    expect(liveRunner(stored, quote([NOV25, bar('2026-11-27', 0.9, 0.95, 0.69, 0.8)]), V1)).toMatchObject({ status: 'stop', price: 0.7 })
  })

  it('reads from the entry day when there is no close stored yet', () => {
    const live = liveRunner({ ...open, lastDay: null, lastClose: null }, quote([NOV24, NOV25]), V1)
    expect(live).toMatchObject({ kind: 'open', day: '2026-11-25', price: 0.8998 })
  })

  it('leaves settled signals alone', () => {
    expect(liveRunner(runner({ status: 'stop' }), quote([NOV24, NOV25]), V1)).toBeNull()
  })
})

describe('liveRunners', () => {
  it("maps each runner with a quote by id, on its rule version's plan or the starting one", () => {
    const quotes = new Map([['BENF', quote([NOV24, NOV25])]])
    const gappy = planRuleOf({ gap_skip: 0.01 })
    const live = liveRunners([runner(), runner({ id: 2, ruleVersion: 0 }), runner({ id: 3, symbol: 'NONE' })], quotes, { 1: gappy })
    expect([...live.keys()]).toEqual([1, 2])
    expect(live.get(1)?.kind).toBe('open') // 0.8376 is under the 0.915 signal close: no gap
    expect(live.get(2)?.kind).toBe('open')
    const up = new Map([['BENF', quote([NOV24, bar('2026-11-25', 0.95, 1, 0.9, 0.97)])]])
    expect(liveRunners([runner()], up, { 1: gappy }).get(1)?.kind).toBe('skipped')
    expect(liveRunners([runner({ ruleVersion: 0 })], up, { 1: gappy }).get(1)?.kind).toBe('open')
  })
})

/** A Yahoo daily chart: each bar at 9:30 New York time (14:30 UTC in November). */
const body = (days: string[], ohlc: (number | null)[][], meta: Record<string, unknown> = {}) => ({
  chart: {
    result: [
      {
        meta: { currency: 'USD', regularMarketTime: Date.parse('2026-11-25T21:00:00Z') / 1000, ...meta },
        timestamp: days.map((d) => Date.parse(`${d}T14:30:00Z`) / 1000),
        indicators: {
          quote: [{ open: ohlc.map((b) => b[0]), high: ohlc.map((b) => b[1]), low: ohlc.map((b) => b[2]), close: ohlc.map((b) => b[3]) }],
        },
      },
    ],
  },
})

describe('parseDaily', () => {
  const after = new Date('2026-11-26T15:00:00Z') // Thanksgiving: Nov 25 is the last session

  it('reads one bar per New York day, oldest first, skipping a bar with a missing price', () => {
    const q = parseDaily(
      body(['2026-11-23', '2026-11-24', '2026-11-25'], [[0.437, 0.495, 0.437, null], [0.654, 1.1, 0.579, 0.915], [0.8376, 0.9876, 0.7532, 0.8998]]),
      after,
    )!
    expect(q.bars).toEqual([NOV24, NOV25])
    expect(q.at).toBe('2026-11-25T21:00:00.000Z')
    expect(q.closed).toBe(true)
  })

  it('keeps the later of two bars for the same day', () => {
    const q = parseDaily(body(['2026-11-25', '2026-11-25'], [[0.8376, 0.95, 0.7532, 0.9], [0.8376, 0.9876, 0.7532, 0.8998]]), after)!
    expect(q.bars).toEqual([NOV25])
  })

  it("is not closed while today's session trades: Yahoo's session end, else 4 PM New York", () => {
    const end = Date.parse('2026-11-25T21:00:00Z') / 1000
    const day = body(['2026-11-25'], [[0.8376, 0.9876, 0.7532, 0.8998]], { currentTradingPeriod: { regular: { start: end - 23_400, end } } })
    expect(parseDaily(day, new Date('2026-11-25T20:42:00Z'))!.closed).toBe(false)
    expect(parseDaily(day, new Date('2026-11-25T21:00:00Z'))!.closed).toBe(true)
    const noPeriod = body(['2026-11-25'], [[0.8376, 0.9876, 0.7532, 0.8998]])
    expect(parseDaily(noPeriod, new Date('2026-11-25T20:59:00Z'))!.closed).toBe(false)
    expect(parseDaily(noPeriod, new Date('2026-11-25T21:01:00Z'))!.closed).toBe(true)
  })

  it('takes nothing but a US$ chart with a bar', () => {
    expect(parseDaily(body(['2026-11-25'], [[1, 1, 1, 1]], { currency: 'CAD' }), after)).toBeNull()
    expect(parseDaily(body([], []), after)).toBeNull()
    expect(parseDaily({ chart: { result: null } }, after)).toBeNull()
    expect(parseDaily(null, after)).toBeNull()
  })
})

describe('fetchRunnerQuotes', () => {
  it("asks Yahoo for 3 months of daily bars under Yahoo's symbol and leaves out one that fails", async () => {
    const urls: string[] = []
    const fake = async (url: string) => {
      urls.push(url)
      return url.includes('/BENF?')
        ? new Response(JSON.stringify(body(['2026-11-25'], [[0.8376, 0.9876, 0.7532, 0.8998]])))
        : new Response('down', { status: 500 })
    }
    const quotes = await fetchRunnerQuotes(['BENF', 'BRK.B', 'BENF'], fake, new Date('2026-11-26T15:00:00Z'))
    expect([...quotes.keys()]).toEqual(['BENF'])
    expect(urls.sort()).toEqual([runnerChartUrl('BENF'), runnerChartUrl('BRK.B')].sort())
    expect(runnerChartUrl('BRK.B')).toMatch(/\/BRK-B\?range=3mo&interval=1d$/)
  })
})
