import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OpenRunnerCard } from './OpenRunnerCard'
import type { Runner } from '@/lib/runners'

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
    expect(text).toContain('Stop US$0.6500 · target US$1.25 · hold by Nov 28')
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
})
