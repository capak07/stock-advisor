import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RunnerCard } from './RunnerCard'
import type { Runner, RunnerWarning } from '@/lib/runners'
import { LIVE_NOTE, type LiveRunner } from '@/lib/runners-live'

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
  signalLow: 0.66,
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
    expect(text).toContain('if it opens near US$1.36: stop US$1.02 (−25.0%), target US$2.04 (+50.0%, 2R)')
    expect(text).toContain('≈ 105 shares') // floor(50 / 1.4 / 0.34)
    expect(text).toContain('Est. spread 2.0% = 0.08R')
    expect(text).toContain('Paper trade: 100 shares at the open (about US$136.00 at the signal close)')
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

  describe("with Yahoo's prices after the open", () => {
    // BENF's 2026-11-24 signal (close 0.915), bought at the Nov 25 open
    const benf = runner({ symbol: 'BENF', signalDay: '2026-11-24', signalClose: 0.915, signalLow: 0.579, stop: 0.68, target: 1.39, spreadPct: 3.13, holdBy: '2026-12-09' })
    const plan = { entry: 0.8376, stop: 0.62, target: 1.27 }
    const bought: LiveRunner = { kind: 'open', entryDay: '2026-11-25', plan, day: '2026-11-25', price: 0.8998, closed: true, at: '2026-11-25T21:00:00Z' }

    it('shows the plan from the real open, what the 100 shares cost and what they are worth', () => {
      const text = render(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper live={bought} />)
      expect(text).toContain('Bought at the open, US$0.8376 on Nov 25: stop US$0.6200 (−26.0%), target US$1.27 (+51.6%, 2R) · hold by Dec 9')
      expect(text).not.toContain('if it opens near')
      expect(text).toContain('≈ 164 shares') // floor(50 / 1.4 / 0.2176)
      expect(text).toContain('Est. spread 3.1% = 0.12R') // 3.13 * 0.8376 / 0.2176 / 100
      expect(text).toContain('Paper trade: 100 shares, US$91.50 at the signal close, bought for US$83.76 at the open')
      expect(text).toContain('Closed US$0.8998 on Nov 25: worth US$89.98 · ')
      expect(text).toMatch(/class="num gain" data-testid="runner-gain">\+US\$6\.22 \(\+7\.4%\) · \+0\.29R</)
      expect(text).toContain(LIVE_NOTE)
    })

    it('shows a stop that was hit as a loss', () => {
      const stopped: LiveRunner = { kind: 'exited', entryDay: '2026-11-25', plan, status: 'stop', day: '2026-11-25', price: 0.62, atOpen: false }
      const text = render(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper live={stopped} />)
      expect(text).toContain('Hit the stop at US$0.6200 on Nov 25: got back US$62.00 · ')
      expect(text).toMatch(/class="num loss" data-testid="runner-gain">−US\$21\.76 \(−26\.0%\) · −1\.00R</)
    })

    it('says when the open skipped the trade', () => {
      const skipped: LiveRunner = { kind: 'skipped', entryDay: '2026-11-25', entry: 1.06, reason: 'gapped up at the open' }
      const text = render(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper live={skipped} />)
      expect(text).toContain('Opened US$1.06 on Nov 25: skipped, gapped up at the open.')
      expect(text).toContain('Paper trade: none, skipped at the open.')
      expect(text).not.toContain('shares at the open')
      expect(text).not.toContain('Est. spread')
      expect(text).not.toContain('runner-gain')
    })

    it('has no live note without live prices', () => {
      expect(render(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper />)).not.toContain(LIVE_NOTE)
    })
  })
})
