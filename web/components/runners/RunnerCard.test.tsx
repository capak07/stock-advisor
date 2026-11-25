import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RunnerCard } from './RunnerCard'
import type { Runner, RunnerWarning } from '@/lib/runners'
import { LIVE_NOTE, type LiveRunner } from '@/lib/runners-live'

const render = (element: ReactElement) => renderToStaticMarkup(element)
/** The card's markup split at its Details fold: what shows, and what waits for a tap. */
const parts = (element: ReactElement) => {
  const [shown, folded = ''] = render(element).split('<details')
  return { shown, folded }
}

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
  it('leads with buying at the open and the plan from the signal close, the rest under Details', () => {
    const { shown, folded } = parts(<RunnerCard runner={runner({ warnings: [SALE], warningsChecked: true })} maxLossCad={50} usdCad={1.4} paper={false} />)
    expect(shown).toContain('<b class="answer-big">Buy at the open</b>')
    expect(shown).toContain('About US$136.00 for 100 shares at the signal close')
    expect(shown).toContain('<span class="label">Entry ≈ US$</span><b>1.36</b><span class="lvl-pct" aria-hidden="true">')
    expect(shown).toMatch(/Target US\$<\/span><b class="gain">2\.04<\/b><span class="lvl-pct num gain">\+50\.0%/)
    expect(shown).toMatch(/Stop US\$<\/span><b class="loss">1\.02<\/b><span class="lvl-pct num loss">−25\.0%/)
    expect(shown).toContain('Hold until Nov 30')
    expect(shown).toContain('<span class="chip review">Share sale</span>') // the warning's chip stays on the card
    expect(folded).toContain('Filed a F-1/A on Nov 20: a share sale may be pending.')
    expect(folded).toContain('Ignition Fri: +102%')
    expect(folded).toContain('≈ 105 shares') // floor(50 / 1.4 / 0.34)
    expect(folded).toContain('Est. spread 2.0% = 0.08R')
    expect(folded).toContain('Paper trade: 100 shares at the open (about US$136.00 at the signal close)')
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

    it('leads with the gain, what the 100 shares cost and are worth, and the plan from the real open', () => {
      const { shown, folded } = parts(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper live={bought} />)
      expect(shown).toContain('<b class="answer-big num gain" data-testid="runner-gain">+US$6.22 +7.4%</b><b class="answer-r num gain">+0.29R</b>')
      expect(shown).toContain('100 shares: paid US$83.76 · worth US$89.98')
      expect(shown).toContain('<span class="label">Bought US$</span><b>0.8376</b><span class="lvl-pct lvl-note">Nov 25</span>')
      expect(shown).toMatch(/<b class="gain">1\.27<\/b><span class="lvl-pct num gain">\+51\.6%/)
      expect(shown).toMatch(/<b class="loss">0\.6200<\/b><span class="lvl-pct num loss">−26\.0%/)
      expect(shown).toContain('Closed US$0.8998 on Nov 25 · hold until Dec 9')
      expect(shown).not.toContain('Buy at the open')
      expect(folded).toContain('≈ 164 shares') // floor(50 / 1.4 / 0.2176)
      expect(folded).toContain('Est. spread 3.1% = 0.12R') // 3.13 * 0.8376 / 0.2176 / 100
      expect(folded).toContain('Paper trade: 100 shares, US$91.50 at the signal close, bought for US$83.76 at the open')
      expect(folded).toContain('Closed US$0.8998 on Nov 25: worth US$89.98')
      expect(folded).toContain(LIVE_NOTE)
    })

    it('shows a stop that was hit as a loss, with no hold line', () => {
      const stopped: LiveRunner = { kind: 'exited', entryDay: '2026-11-25', plan, status: 'stop', day: '2026-11-25', price: 0.62, atOpen: false }
      const { shown } = parts(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper live={stopped} />)
      expect(shown).toContain('<b class="answer-big num loss" data-testid="runner-gain">−US$21.76 −26.0%</b><b class="answer-r num loss">−1.00R</b>')
      expect(shown).toContain('100 shares: paid US$83.76 · got back US$62.00')
      expect(shown).toContain('Hit the stop at US$0.6200 on Nov 25</p>')
      expect(shown).not.toContain('hold until')
    })

    it('says when the open skipped the trade, without tiles', () => {
      const skipped: LiveRunner = { kind: 'skipped', entryDay: '2026-11-25', entry: 1.06, reason: 'gapped up at the open' }
      const { shown, folded } = parts(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper live={skipped} />)
      expect(shown).toContain('<b class="answer-big">Skipped</b><span class="answer-note">Opened US$1.06 on Nov 25: gapped up at the open</span>')
      expect(shown).not.toContain('dt-levels')
      expect(shown).not.toContain('Hold until')
      expect(folded).toContain('Paper trade: none, skipped at the open.')
      expect(folded).not.toContain('Est. spread')
      expect(shown + folded).not.toContain('runner-gain')
    })

    it('has no live note without live prices', () => {
      expect(render(<RunnerCard runner={benf} maxLossCad={50} usdCad={1.4} paper />)).not.toContain(LIVE_NOTE)
    })
  })
})
