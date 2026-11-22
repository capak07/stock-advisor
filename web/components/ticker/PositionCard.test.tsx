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

const render = (held: HeldPlan[], positions = [position('tfsa')]) =>
  renderToStaticMarkup(
    <PositionCard
      symbol="RY.TO"
      assetType="stock"
      positions={positions}
      held={held}
      price={120}
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

  it('shows no chips without an action row', () => {
    expect(render([])).not.toContain('class="chip')
  })
})
