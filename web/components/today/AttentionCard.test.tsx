import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AttentionCard } from './AttentionCard'
import type { ActionKind, HoldingAction } from '@/lib/portfolio/actions'
import type { HoldingRow } from '@/lib/portfolio/view'

const holding = (symbol: string, kind: ActionKind, reasons: string[], gainPct: number, review = false): HoldingRow => ({
  key: `tfsa:stock:${symbol}`,
  account: 'tfsa',
  symbol,
  name: null,
  market: 'TSX',
  valueCad: 100,
  gainCad: gainPct,
  gainPct,
  action: { account: 'tfsa', symbol, assetType: 'stock', action: kind, review, reasons, warnings: [] } as unknown as HoldingAction,
  notes: [],
})

describe('AttentionCard', () => {
  it('says nothing needs attention when nothing does (Review Focus 1)', () => {
    const html = renderToStaticMarkup(<AttentionCard items={[]} onHold={0} warnings={[]} asOf={null} />)
    expect(html).toContain('Nothing needs your attention')
    expect(html).not.toContain('on Hold')
  })

  it('shows each item with its chip, symbol, reason and P/L, then the Holds and the warnings', () => {
    const html = renderToStaticMarkup(
      <AttentionCard
        items={[holding('SHOP.TO', 'sell', ['closed below its stop'], -6.1), holding('T.TO', 'hold', ['steady', 'takeover bid'], 31.8, true)]}
        onHold={5}
        warnings={[{ title: 'TFSA round trips', detail: 'TFSA: 4 round trips this year.' }]}
        asOf="Fri 3:15 PM"
      />,
    )
    expect(html).toContain('chip sell')
    expect(html).toContain('SHOP.TO')
    expect(html).toContain('Closed below its stop')
    expect(html).toContain('−6.1%')
    expect(html).toContain('chip review')
    expect(html).toContain('Takeover bid')
    expect(html).toContain('5 more on Hold')
    expect(html).toContain('href="/portfolio"')
    expect(html).toContain('TFSA: 4 round trips this year.')
    expect(html).not.toContain('Nothing needs your attention')
  })

  it('shows the warnings even when nothing needs action', () => {
    const html = renderToStaticMarkup(
      <AttentionCard items={[]} onHold={2} warnings={[{ title: 'A trade was left out', detail: 'A sell of 5 X has no buy.' }]} asOf={null} />,
    )
    expect(html).toContain('Nothing needs your attention')
    expect(html).toContain('2 on Hold')
    expect(html).toContain('A sell of 5 X has no buy.')
  })
})
