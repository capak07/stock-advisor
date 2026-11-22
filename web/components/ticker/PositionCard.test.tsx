import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { HeldPlan } from '@/lib/data/ticker'
import type { Position } from '@/lib/portfolio/types'
import { PositionCard } from './PositionCard'

const position = (account: Position['account']): Position => ({
  account,
  symbol: 'RY.TO',
  assetType: 'stock',
  qty: 10,
  costCad: 1000,
  openedOn: '2026-09-01',
})

const plan = (over: Partial<HeldPlan>): HeldPlan => ({
  account: 'tfsa',
  action: 'hold',
  review: false,
  exitPlan: null,
  refPrice: null,
  ...over,
})

const LATEST = { day: '2026-11-20', close: 120, currency: 'CAD' as const }
const PREVIOUS = { day: '2026-11-19', close: 115, currency: 'CAD' as const }

const render = (held: HeldPlan[], positions = [position('tfsa')], today = '2026-11-20') =>
  renderToStaticMarkup(
    <PositionCard
      symbol="RY.TO"
      assetType="stock"
      positions={positions}
      held={held}
      latest={LATEST}
      previous={PREVIOUS}
      today={today}
      currency="CAD"
      usdCad={1.4}
      benchmark="XIU.TO"
    />,
  )

describe('PositionCard', () => {
  it("shows the run's action, and a Review chip beside it when the run flags a review, as My Portfolio does", () => {
    const flagged = render([plan({ action: 'hold', review: true })])
    expect(flagged).toContain('<span class="chip hold">Hold</span>')
    expect(flagged).toContain('<span class="chip review">Review</span>')

    const plain = render([plan({ action: 'trim' })])
    expect(plain).toContain('<span class="chip trim">Trim</span>')
    expect(plain).not.toContain('Review')
  })

  it('flags each account on its own', () => {
    const html = render(
      [plan({ account: 'tfsa', action: 'sell', review: true }), plan({ account: 'non_registered', action: 'add' })],
      [position('tfsa'), position('non_registered')],
    )
    const [tfsa, taxable] = html.split('data-testid="position"').slice(1)
    expect(tfsa).toContain('chip review')
    expect(taxable).toContain('chip add')
    expect(taxable).not.toContain('chip review')
  })

  it("shows the value, average cost, today's return and the all-time return, in that order", () => {
    const html = render([])
    const labels = [...html.matchAll(/<span class="label">([^<]+)<\/span><b/g)].map((m) => m[1])
    expect(labels).toEqual(['Value', 'Avg cost', 'Today', 'All-time'])
    expect(html).toContain('<b class="num gain">+C$50</b><span class="num sub">+4.3%</span>') // 10 × C$5 since C$115
    expect(html).toContain('<b class="num gain">+C$200</b><span class="num sub">+20.0%</span>') // C$1,200 on C$1,000
    expect(html).not.toContain('on Thu')
  })

  it("names the day of today's return when the last close is older (a weekend)", () => {
    expect(render([], [position('tfsa')], '2026-11-22')).toContain('Today <span class="sub">on Fri</span>')
  })

  it('shows no chips without an action row', () => {
    expect(render([])).not.toContain('class="chip')
  })
})
