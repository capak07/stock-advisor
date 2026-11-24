import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RunnerCard } from './RunnerCard'
import type { Runner, RunnerWarning } from '@/lib/runners'

const render = (element: ReactElement) => renderToStaticMarkup(element)

const SALE: RunnerWarning = {
  kind: 'share_sale',
  form: 'F-1/A',
  filed: '2026-11-20',
  text: 'Filed a F-1/A on Nov 20: a share sale may be pending.',
}

/** AKAN's 2026-11-13 ignition, waiting for the next open. */
const runner = (over: Partial<Runner> = {}): Runner => ({
  id: 1,
  signalDay: '2026-11-13',
  symbol: 'AKAN',
  name: 'Akanda Corp.',
  ruleVersion: 0,
  changePct: 102.38,
  volumeX: 77.2,
  dollarVolume: 121_326_960,
  closePos: 0.651,
  signalClose: 1.36,
  spreadPct: 2,
  costR: 0.08,
  warnings: [],
  warningsChecked: true,
  status: 'waiting',
  skipReason: null,
  entryDay: null,
  entry: null,
  stop: 1.02,
  target: 2.04,
  holdBy: '2026-11-30',
  lastDay: null,
  lastClose: null,
  exitDay: null,
  exitPrice: null,
  grossR: null,
  netR: null,
  ...over,
})

describe('RunnerCard', () => {
  it('shows the plan from the signal close, the shares and the warning', () => {
    const text = render(<RunnerCard runner={runner({ warnings: [SALE], warningsChecked: true })} maxLossCad={50} usdCad={1.4} paper={false} />)
    expect(text).toContain('Filed a F-1/A on Nov 20: a share sale may be pending.')
    expect(text).toContain('if it opens near US$1.36: stop US$1.02, target US$2.04 (2R)')
    expect(text).toContain('≈ 105 shares') // floor(50 / 1.4 / 0.34)
    expect(text).toContain('Est. spread 2.0% = 0.08R')
  })

  it('says when the filings were not checked', () => {
    expect(render(<RunnerCard runner={runner({ warnings: [], warningsChecked: false })} maxLossCad={50} usdCad={1.4} paper={false} />)).toContain('Filings not checked')
  })

  it('carries the paper label while the gate has not passed', () => {
    expect(render(<RunnerCard runner={runner()} maxLossCad={50} usdCad={1.4} paper />)).toContain('Paper: testing')
    expect(render(<RunnerCard runner={runner()} maxLossCad={50} usdCad={1.4} paper={false} />)).not.toContain('Paper: testing')
  })

  it('says when one share already risks more than the max loss', () => {
    // C$1 at 1.40 = US$0.71, under the US$0.86 a share risks from US$1.36 to US$0.50
    const text = render(<RunnerCard runner={runner({ stop: 0.5 })} maxLossCad={1} usdCad={1.4} paper={false} />)
    expect(text).toContain('Even one share risks more than your C$1 limit.')
    expect(text).not.toContain('Filings not checked')
  })
})
