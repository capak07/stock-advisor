import { describe, expect, it } from 'vitest'
import {
  checkView,
  gate,
  ignitionLine,
  paperTotal,
  paperValue,
  recordOf,
  rSoFar,
  type Backtest,
  type BacktestReport,
  type Runner,
} from './runners'

/** AKAN's 2026-11-13 ignition, entered at the 2026-11-16 open. */
const runner = (over: Partial<Runner> = {}): Runner => ({
  id: 1,
  signalDay: '2026-11-13',
  symbol: 'AKAN',
  name: 'Akanda Corp.',
  ruleVersion: 1,
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
  status: 'open',
  skipReason: null,
  entryDay: '2026-11-16',
  entry: 1.92,
  stop: 1.44,
  target: 2.88,
  holdBy: '2026-11-30',
  lastDay: '2026-11-17',
  lastClose: 2.1,
  exitDay: null,
  exitPrice: null,
  grossR: null,
  netR: null,
  ...over,
})

const report = (over: Partial<BacktestReport> = {}): BacktestReport => ({
  signals: 300,
  skipped_gap: 0,
  skipped_other: 0,
  target: 100,
  stop: 150,
  held: 50,
  avg_net_r: 0.1,
  median_net_r: 0,
  lost_over_1r: 0.05,
  worst: [],
  ...over,
})

const backtest = ({ ruleVersion, newer }: { ruleVersion: number | null; newer: Partial<BacktestReport> }): Backtest => ({
  ranAt: '2026-11-22T10:00:00Z',
  dataFrom: '2018-11-01',
  dataTo: '2026-11-20',
  cutoff: '2024-03-01',
  variantsTried: 15,
  ruleVersion,
  frozen: { older: report(), newer: report(newer) },
  pick: { name: 'starting values', note: null, older: report(), newer: report(newer) },
})

describe('runners', () => {
  it('summarises closed runners after costs, leaving skips out of the averages', () => {
    const rows = [runner({ status: 'target', netR: 1.5 }), runner({ status: 'stop', netR: -0.5 }), runner({ status: 'skipped', netR: null }), runner({ status: 'open', netR: null })]
    expect(recordOf(rows)).toEqual({ count: 2, target: 1, stop: 1, held: 0, skipped: 1, avgNetR: 0.5, medianNetR: 0.5, sumNetR: 1 })
  })

  it('keeps the paper label until the backtest and the live record both show a profit', () => {
    const closed = Array.from({ length: 40 }, () => runner({ status: 'target', netR: 0.5, ruleVersion: 1, signalDay: '2026-09-01' }))
    const good = backtest({ ruleVersion: 1, newer: { signals: 120, avg_net_r: 0.2 } })
    expect(gate(1, good, closed, '2026-11-24').passed).toBe(true)
    expect(gate(1, good, closed.slice(1), '2026-11-24').reasons).toEqual(['39 of 40 closed live signals so far.'])
    expect(gate(1, good, closed, '2026-10-15').reasons).toEqual(['The live record is under 2 months old.'])
    expect(gate(1, backtest({ ruleVersion: 1, newer: { signals: 120, avg_net_r: -0.1 } }), closed, '2026-11-24').passed).toBe(false)
    expect(gate(1, backtest({ ruleVersion: 1, newer: { signals: 99, avg_net_r: 0.4 } }), closed, '2026-11-24').passed).toBe(false)
    expect(gate(2, good, closed, '2026-11-24').passed).toBe(false) // another version's record
    expect(gate(0, null, [], '2026-11-24').reasons).toEqual(['No rule has been chosen by a backtest yet.'])
  })

  it('names each failed part of the gate, in order', () => {
    const closed = Array.from({ length: 40 }, () => runner({ status: 'stop', netR: -1.1, ruleVersion: 1, signalDay: '2026-11-01' }))
    expect(gate(1, backtest({ ruleVersion: 1, newer: { signals: 99, avg_net_r: -0.1 } }), closed.slice(5), '2026-11-24').reasons).toEqual([
      '99 of 100 backtest signals in the unseen third.',
      'The backtest lost money on the unseen third after costs.',
      '35 of 40 closed live signals so far.',
      'The live record is under 2 months old.',
      'The live record is losing after costs.',
    ])
    expect(gate(2, backtest({ ruleVersion: 1, newer: {} }), closed, '2026-11-24').reasons).toEqual([
      'No backtest of this rule yet.',
      '0 of 40 closed live signals so far.',
      'The live record is under 2 months old.',
    ])
    expect(gate(1, null, closed, '2026-11-24').reasons[0]).toBe('No backtest of this rule yet.')
  })

  it('counts only closed runners toward the live record', () => {
    const rows = [
      ...Array.from({ length: 39 }, () => runner({ status: 'held', netR: 0.2, signalDay: '2026-09-01' })),
      runner({ status: 'skipped', netR: null, signalDay: '2026-08-01' }),
      runner({ status: 'open', netR: null }),
    ]
    const good = backtest({ ruleVersion: 1, newer: { signals: 120, avg_net_r: 0.2 } })
    expect(gate(1, good, rows, '2026-11-24').reasons).toEqual(['39 of 40 closed live signals so far.'])
  })

  it('fails closed on a missing average', () => {
    const closed = Array.from({ length: 40 }, () => runner({ status: 'target', netR: 0.5, ruleVersion: 1, signalDay: '2026-09-01' }))
    const good = backtest({ ruleVersion: 1, newer: { signals: 120, avg_net_r: 0.2 } })
    expect(gate(1, backtest({ ruleVersion: 1, newer: { signals: 120, avg_net_r: null } }), closed, '2026-11-24').reasons).toEqual([
      'The backtest lost money on the unseen third after costs.',
    ])
    const unpriced = closed.map((r) => ({ ...r, netR: null }))
    expect(gate(1, good, unpriced, '2026-11-24').reasons).toEqual(['The live record is losing after costs.'])
  })

  it("says how the morning check went and what the signals section is", () => {
    expect(checkView(null, '2026-11-24')).toEqual({
      lines: [{ failed: false, text: 'No check has run yet.' }],
      current: true,
      empty: 'No ignition yesterday.',
    })
    expect(checkView({ day: '2026-11-24', error: null }, '2026-11-24')).toEqual({ lines: [], current: true, empty: 'No ignition yesterday.' })
    expect(checkView({ day: '2026-11-24', error: 'RuntimeError: boom' }, '2026-11-24')).toEqual({
      lines: [{ failed: true, text: "This morning's check failed: RuntimeError: boom" }],
      current: false,
      empty: 'No signals: the check failed.',
    })
    expect(checkView({ day: '2026-11-23', error: null }, '2026-11-24')).toEqual({
      lines: [{ failed: false, text: "This morning's check has not run yet. Last check: Mon, Nov 23." }],
      current: false,
      empty: 'No ignition at the last check.',
    })
    expect(checkView({ day: '2026-11-20', error: 'RuntimeError: boom' }, '2026-11-24').lines).toEqual([
      { failed: false, text: "This morning's check has not run yet. Last check: Fri, Nov 20." },
      { failed: true, text: 'The check on Fri, Nov 20 failed: RuntimeError: boom' },
    ])
  })

  it('says what the ignition day did', () => {
    expect(ignitionLine(runner({ signalDay: '2026-11-13', changePct: 102.38, volumeX: 892.11, dollarVolume: 121_326_960, signalClose: 1.36, closePos: 0.651 })))
      .toBe("Ignition Fri: +102% on 89M shares (892× normal), closed at 65% of the day's range")
    expect(ignitionLine(runner({ signalDay: '2026-11-16', changePct: 24.6, volumeX: 12.4, dollarVolume: 2_400_000, signalClose: 4, closePos: 1 })))
      .toBe("Ignition Mon: +25% on 600K shares (12× normal), closed at 100% of the day's range")
  })

  it('measures an open runner in R', () => {
    expect(rSoFar(runner({ status: 'open', lastClose: 2.4 }))).toBeCloseTo(1.0)
    expect(rSoFar(runner({ status: 'waiting', entry: null }))).toBeNull()
    expect(rSoFar(runner({ status: 'open', lastClose: null }))).toBeNull()
  })

  it('values 100 paper shares in US$ to the cent', () => {
    const cheap = paperValue(0.85, 0.93)
    expect(cheap).toMatchObject({ cost: 85, value: 93, gain: 8 })
    expect(cheap?.gainPct).toBeCloseTo(9.41, 2)
    expect(paperValue(1.92, 2.4)).toEqual({ cost: 192, value: 240, gain: 48, gainPct: 25 })
    expect(paperValue(null, 2)).toBeNull()
    expect(paperValue(1, null)).toBeNull()
  })

  it('totals the finished paper trades, before and after the spread', () => {
    const rows = [
      runner({ symbol: 'MULN', status: 'target', entry: 2, exitPrice: 3, spreadPct: 2 }),
      runner({ symbol: 'SNDL', status: 'stop', entry: 1.5, exitPrice: 1.2, spreadPct: 2 }),
      runner({ symbol: 'SKIP', status: 'skipped', entry: null, exitPrice: null }),
      runner({ symbol: 'OPEN', status: 'open', exitPrice: null }),
    ]
    expect(paperTotal(rows)).toEqual({ trades: 2, cost: 350, value: 420, gain: 70, gainPct: 20, spread: 7, gainAfterSpread: 63 })
    expect(paperTotal([])).toEqual({ trades: 0, cost: 0, value: 0, gain: 0, gainPct: 0, spread: 0, gainAfterSpread: 0 })
  })
})
