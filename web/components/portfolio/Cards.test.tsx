import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { HoldingsCard } from './Cards'
import type { ActionKind, HoldingAction } from '@/lib/portfolio/actions'
import type { HoldingRow } from '@/lib/portfolio/view'

const action = (symbol: string, kind: ActionKind): HoldingAction =>
  ({
    account: 'tfsa',
    symbol,
    assetType: 'stock',
    action: kind,
    review: false,
    reasons: [],
    warnings: [],
    trailingStop: null,
    q10: null,
    q50: null,
    q90: null,
    horizonDays: null,
    exitBy: null,
    riskLevel: null,
    exitPlan: null,
    refPrice: null,
  }) as unknown as HoldingAction

const holding = (symbol: string, valueCad: number, kind: ActionKind | null): HoldingRow => ({
  key: `tfsa:stock:${symbol}`,
  account: 'tfsa',
  symbol,
  name: null,
  market: 'TSX',
  valueCad,
  gainCad: 0,
  gainPct: 0,
  action: kind === null ? null : action(symbol, kind),
  notes: [],
  priceMove: null,
})

/** The markup of one holding's row. */
const rowOf = (html: string, symbol: string) => html.split('<tr>').find((row) => row.includes(`>${symbol}</a>`)) ?? ''

describe('HoldingsCard', () => {
  const render = (holdings: HoldingRow[], qtys = new Map<string, number>()) =>
    renderToStaticMarkup(<HoldingsCard holdings={holdings} accounts={1} guides={new Map()} qtys={qtys} asOf="2026-11-20" />)

  it("shows each holding's shares, value and weight, and draws the weight bar orange only on a Trim", () => {
    const html = render(
      [holding('NVDA.TO', 600, 'trim'), holding('RY.TO', 300, 'hold'), holding('T.TO', 100, null)],
      new Map([['tfsa:stock:NVDA.TO', 8.5]]),
    )
    const nvda = rowOf(html, 'NVDA.TO')
    expect(nvda).toContain('8.5')
    expect(nvda).toContain('C$600')
    expect(nvda).toContain('60.0%')
    expect(nvda).toContain('class="weight trim"')
    // the largest holding fills the bar once it is over 20% of the portfolio
    expect(nvda).toContain('width:100%')
    const ry = rowOf(html, 'RY.TO')
    expect(ry).toContain('30.0%')
    expect(ry).toContain('class="weight"')
    expect(ry).toContain('width:50%')
    expect(rowOf(html, 'T.TO')).toContain('class="weight"')
    expect(html).toContain('actions as of Nov 20')
  })

  it("marks each holding's value with the way its price moved, so a Refresh flashes it", () => {
    const html = render([
      { ...holding('UP.TO', 300, 'hold'), priceMove: 'up' },
      { ...holding('DN.TO', 200, 'hold'), priceMove: 'down' },
      holding('NO.TO', 100, null),
    ])
    expect(rowOf(html, 'UP.TO')).toContain('class="r num h-value" data-price="up"')
    expect(rowOf(html, 'DN.TO')).toContain('class="r num h-value" data-price="down"')
    expect(rowOf(html, 'NO.TO')).not.toContain('data-price')
  })

  it('draws small weights on a 20% scale', () => {
    const html = render([holding('A.TO', 100, 'hold'), ...Array.from({ length: 9 }, (_, i) => holding(`B${i}.TO`, 100, 'hold'))])
    expect(rowOf(html, 'A.TO')).toContain('10.0%')
    expect(rowOf(html, 'A.TO')).toContain('width:50%')
  })

  it('leaves out the Action column before the model has run', () => {
    const html = render([holding('RY.TO', 100, null)])
    expect(html).not.toContain('>Action</th>')
    expect(html).toContain('appear once the model runs')
  })
})
