import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { FinishedRunners } from './FinishedRunners'
import type { Runner } from '@/lib/runners'

const render = (element: ReactElement) => renderToStaticMarkup(element)

/** A runner that hit its target on 2026-11-24 under rule version 1. */
const runner = (over: Partial<Runner> = {}): Runner => ({
  id: 1,
  signalDay: '2026-11-18',
  symbol: 'MULN',
  name: null,
  ruleVersion: 1,
  changePct: 60,
  volumeX: 40,
  dollarVolume: 9_000_000,
  closePos: 0.8,
  signalClose: 1.9,
  spreadPct: 2,
  costR: 0.08,
  warnings: [],
  warningsChecked: true,
  status: 'target',
  skipReason: null,
  entryDay: '2026-11-19',
  entry: 2,
  stop: 1.5,
  target: 3,
  holdBy: '2026-12-03',
  lastDay: '2026-11-24',
  lastClose: 3.1,
  exitDay: '2026-11-24',
  exitPrice: 3,
  grossR: 2,
  netR: 1.92,
  ...over,
})

const items = (html: string) => html.match(/<li>/g)?.length ?? 0

describe('FinishedRunners', () => {
  it("totals the live version's finished trades and lists each in US$", () => {
    const closed = [
      runner(),
      runner({ id: 2, symbol: 'SNDL', status: 'stop', entry: 1.5, exitPrice: 1.2 }),
      runner({ id: 3, symbol: 'OLD', ruleVersion: 0, entry: 1, exitPrice: 5 }),
    ]
    const text = render(<FinishedRunners closed={closed} version={1} />)
    expect(text).toContain(
      '2 finished trades: put in US$350.00, got back US$420.00, +US$70.00 (+20.0%). After the estimated spread: +US$63.00.',
    )
    expect(text).toContain(
      ' · bought at US$2.00 = US$200.00 · sold at US$3.00 = US$300.00 (target, Nov 24) · <span class="num gain">+US$100.00 (+50.0%)</span>',
    )
    expect(text).toContain(
      ' · bought at US$1.50 = US$150.00 · sold at US$1.20 = US$120.00 (stop, Nov 24) · <span class="num loss">−US$30.00 (−20.0%)</span>',
    )
    expect(text).toContain('href="/ticker/MULN"')
    expect(text).not.toContain('OLD')
  })

  it('says time ran out for a trade held to its last day, and counts one trade in the singular', () => {
    const text = render(<FinishedRunners closed={[runner({ status: 'held', exitPrice: 2.2 })]} version={1} />)
    expect(text).toContain('(time up, Nov 24)')
    expect(text).toContain('1 finished trade: put in US$200.00')
  })

  it('leaves out skipped trades and lists at most 20', () => {
    const many = Array.from({ length: 21 }, (_, i) => runner({ id: i + 1, symbol: `T${i}` }))
    const skipped = runner({ id: 99, symbol: 'SKIP', status: 'skipped', entry: null, exitPrice: null })
    const text = render(<FinishedRunners closed={[skipped, ...many]} version={1} />)
    expect(items(text)).toBe(20)
    expect(text).toContain('21 finished trades:')
    expect(text).not.toContain('SKIP')
  })

  it('says when no paper trade has finished yet', () => {
    expect(render(<FinishedRunners closed={[]} version={1} />)).toContain('No finished paper trades yet.')
  })
})
