import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OpenRunnerCard } from './OpenRunnerCard'
import type { Runner } from '@/lib/runners'
import { LIVE_NOTE, type LiveRunner } from '@/lib/runners-live'

const render = (element: ReactElement) => renderToStaticMarkup(element)
/** The card's markup split at its Details fold: what shows, and what waits for a tap. */
const parts = (element: ReactElement) => {
  const [shown, folded = ''] = render(element).split('<details')
  return { shown, folded }
}

/** A sub-dollar runner entered at the 2026-11-17 open, priced at the next close. */
const runner = (over: Partial<Runner> = {}): Runner => ({
  id: 1,
  signalDay: '2026-11-14',
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
  status: 'open',
  skipReason: null,
  entryDay: '2026-11-17',
  entry: 0.85,
  stop: 0.65,
  target: 1.25,
  holdBy: '2026-11-28',
  lastDay: '2026-11-18',
  lastClose: 0.93,
  exitDay: null,
  exitPrice: null,
  grossR: null,
  netR: null,
  ...over,
})

describe('OpenRunnerCard', () => {
  it('leads with the 100 paper shares\' gain and R at the last close, then the bought / target / stop tiles', () => {
    const { shown, folded } = parts(<OpenRunnerCard runner={runner()} />)
    expect(shown).toContain('<b class="answer-big num gain" data-testid="open-runner-gain">+US$8.00 +9.4%</b>')
    expect(shown).toContain('<b class="answer-r num gain" data-testid="open-runner-r">+0.40R</b>')
    expect(shown).toContain('100 shares: paid US$85.00 · worth US$93.00')
    expect(shown).toContain('<span class="label">Bought US$</span><b>0.8500</b><span class="lvl-pct lvl-note">Nov 17</span>')
    expect(shown).toMatch(/<b class="gain">1\.25<\/b><span class="lvl-pct num gain">\+47\.1%/)
    expect(shown).toMatch(/<b class="loss">0\.6500<\/b><span class="lvl-pct num loss">−23\.5%/)
    expect(shown).toContain('Nov 18 close US$0.9300 · hold until Nov 28')
    expect(folded).toContain('Bought 100 shares at US$0.8500 on Nov 17 = US$85.00')
    expect(folded).toContain('Nov 18 close US$0.9300 (the last morning check): worth US$93.00')
    expect(folded).toContain('R so far +0.40R')
  })

  it('shows a loss as a loss', () => {
    expect(render(<OpenRunnerCard runner={runner({ lastClose: 0.8 })} />)).toContain(
      '<b class="answer-big num loss" data-testid="open-runner-gain">−US$5.00 −5.9%</b>',
    )
  })

  it('says when there is no close yet', () => {
    const text = render(<OpenRunnerCard runner={runner({ lastClose: null, lastDay: null })} />)
    expect(text).toContain('<b class="answer-big">No close yet</b>')
    expect(text).not.toContain('worth')
  })

  describe("with Yahoo's prices past the stored close", () => {
    const plan = { entry: 0.85, stop: 0.65, target: 1.25 }

    it('leads with the latest price in place of the stored close, with its R', () => {
      const live: LiveRunner = { kind: 'open', entryDay: '2026-11-17', plan, day: '2026-11-19', price: 0.95, closed: false, at: '2026-11-19T19:05:00Z' }
      const { shown, folded } = parts(<OpenRunnerCard runner={runner()} live={live} />)
      expect(shown).toContain('<b class="answer-big num gain" data-testid="open-runner-gain">+US$10.00 +11.8%</b>')
      expect(shown).toContain('<b class="answer-r num gain" data-testid="open-runner-r">+0.50R</b>')
      expect(shown).toContain('100 shares: paid US$85.00 · worth US$95.00')
      expect(shown).toContain('Now US$0.9500 at 2:05 PM ET · hold until Nov 28')
      expect(folded).toContain('Now US$0.9500 at 2:05 PM ET: worth US$95.00')
      expect(folded).toContain('Nov 18 close US$0.9300 (the last morning check): worth US$93.00')
      expect(folded).toContain(LIVE_NOTE)
    })

    it('shows a target hit since the stored close, with its R at the exit', () => {
      const live: LiveRunner = { kind: 'exited', entryDay: '2026-11-17', plan, status: 'target', day: '2026-11-19', price: 1.25, atOpen: false }
      const { shown, folded } = parts(<OpenRunnerCard runner={runner()} live={live} />)
      expect(shown).toContain('<b class="answer-big num gain" data-testid="open-runner-gain">+US$40.00 +47.1%</b>')
      expect(shown).toContain('+2.00R')
      expect(shown).toContain('100 shares: paid US$85.00 · got back US$125.00')
      expect(shown).toContain('Hit the target at US$1.25 on Nov 19</p>')
      expect(shown).not.toContain('hold until')
      expect(folded).toContain('R at the exit +2.00R')
    })

    it('has no live note without live prices', () => {
      expect(render(<OpenRunnerCard runner={runner()} />)).not.toContain(LIVE_NOTE)
    })
  })
})
