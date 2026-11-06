import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { PickCard } from './PickCard'
import type { PickView } from '@/lib/data/picks'

const NOTE = 'Price and sector only: TSX stocks have no company filings in this model, so weigh this call accordingly.'

const pick = (basis: string | null): PickView => ({
  id: 1,
  symbol: basis ? 'RY.TO' : 'AAPL',
  name: null,
  sector: null,
  market: basis ? 'TSX' : 'US',
  style: 'position',
  rank: 1,
  horizon: 63,
  q10: -0.02,
  q50: 0.04,
  q90: 0.1,
  pBeat: 0.62,
  exitBy: '2027-01-19',
  entry: 100,
  stop: 90,
  riskLevel: 'medium',
  maxPositionPct: 3,
  topFactors: [],
  catalysts: [],
  cost: null,
  basis,
  benchmark: basis ? 'XIU.TO' : 'SPY',
  atrPct: null,
  dollarVolume20: null,
  chosenBy: 'p',
  scoreRank: null,
  scoreOf: null,
})

describe('PickCard rank', () => {
  it('shows a rank pick by its place, not a percentage', () => {
    const html = renderToStaticMarkup(
      <PickCard
        pick={{ ...pick(null), chosenBy: 'rank', scoreRank: 2, scoreOf: 40, pBeat: 0.62 }}
        portfolioCad={null}
        usdFxFeePct={1.5}
      />,
    )
    const text = html.replaceAll('&#x27;', "'")
    expect(text).toContain('Ranked #2 of 40 by the model')
    expect(text).toContain("Chosen by rank: its probabilities run high, so it's shown by its place in the ranking.")
    expect(text).not.toContain('62%')
  })

  it('a rank row without its place falls back to the P line', () => {
    const html = renderToStaticMarkup(
      <PickCard pick={{ ...pick(null), chosenBy: 'rank', scoreRank: null, scoreOf: null }} portfolioCad={null} usdFxFeePct={1.5} />,
    )
    expect(html).toContain('62%')
    expect(html).not.toContain('Ranked #')
  })

  it('renders a P pick as before', () => {
    const html = renderToStaticMarkup(
      <PickCard pick={{ ...pick(null), chosenBy: 'p', scoreRank: null, scoreOf: null }} portfolioCad={null} usdFxFeePct={1.5} />,
    )
    expect(html).toContain('Beats SPY')
    expect(html).toContain('62%')
    expect(html).not.toContain('Ranked #')
    expect(html).not.toContain('Chosen by rank')
  })
})

describe('PickCard basis', () => {
  it('renders the filings note under P(beat) when the pick carries one', () => {
    const html = renderToStaticMarkup(<PickCard pick={pick(NOTE)} portfolioCad={null} usdFxFeePct={1.5} />)
    const beats = html.indexOf('Beats')
    const note = html.indexOf(NOTE)
    expect(beats).toBeGreaterThan(-1)
    expect(note).toBeGreaterThan(beats)
  })

  it('renders nothing for the note when the pick has none', () => {
    const html = renderToStaticMarkup(<PickCard pick={pick(null)} portfolioCad={null} usdFxFeePct={1.5} />)
    expect(html).not.toContain(NOTE)
    expect(html).not.toContain('data-basis')
  })
})
