import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OpenRunnerCard } from './OpenRunnerCard'
import type { Runner } from '@/lib/runners'
import { LIVE_NOTE, type LiveRunner } from '@/lib/runners-live'

const render = (element: ReactElement) => renderToStaticMarkup(element)

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
  it('shows 100 paper shares bought, what they are worth now and the plan', () => {
    const text = render(<OpenRunnerCard runner={runner()} />)
    expect(text).toContain('Bought 100 shares at US$0.8500 on Nov 17 = US$85.00')
    expect(text).toContain('Now US$0.9300 (Nov 18 close) · worth US$93.00 · ')
    expect(text).toMatch(/class="num gain"[^>]*>\+US\$8\.00 \(\+9\.4%\)</)
    expect(text).toContain('Stop US$0.6500 (−23.5%) · target US$1.25 (+47.1%) · hold by Nov 28')
    expect(text).toContain('+0.40R')
  })

  it('shows a loss as a loss', () => {
    expect(render(<OpenRunnerCard runner={runner({ lastClose: 0.8 })} />)).toMatch(/class="num loss"[^>]*>−US\$5\.00 \(−5\.9%\)</)
  })

  it('says when there is no close yet', () => {
    const text = render(<OpenRunnerCard runner={runner({ lastClose: null, lastDay: null })} />)
    expect(text).toContain('No close yet.')
    expect(text).not.toContain('worth')
  })

  describe("with Yahoo's prices past the stored close", () => {
    const plan = { entry: 0.85, stop: 0.65, target: 1.25 }

    it('shows the latest price in place of the stored close, with its R', () => {
      const live: LiveRunner = { kind: 'open', entryDay: '2026-11-17', plan, day: '2026-11-19', price: 0.95, closed: false, at: '2026-11-19T19:05:00Z' }
      const text = render(<OpenRunnerCard runner={runner()} live={live} />)
      expect(text).toContain('Bought 100 shares at US$0.8500 on Nov 17 = US$85.00')
      expect(text).toContain('Now US$0.9500 at 2:05 PM ET: worth US$95.00 · ')
      expect(text).not.toContain('Nov 18 close')
      expect(text).toMatch(/class="num gain" data-testid="open-runner-gain">\+US\$10\.00 \(\+11\.8%\)</)
      expect(text).toContain('R so far ')
      expect(text).toContain('+0.50R')
      expect(text).toContain(LIVE_NOTE)
    })

    it('shows a target hit since the stored close, with its R at the exit', () => {
      const live: LiveRunner = { kind: 'exited', entryDay: '2026-11-17', plan, status: 'target', day: '2026-11-19', price: 1.25, atOpen: false }
      const text = render(<OpenRunnerCard runner={runner()} live={live} />)
      expect(text).toContain('Hit the target at US$1.25 on Nov 19: got back US$125.00 · ')
      expect(text).toMatch(/\+US\$40\.00 \(\+47\.1%\)/)
      expect(text).toContain('R at the exit ')
      expect(text).toContain('+2.00R')
    })

    it('has no live note without live prices', () => {
      expect(render(<OpenRunnerCard runner={runner()} />)).not.toContain(LIVE_NOTE)
    })
  })
})
