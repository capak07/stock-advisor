import { describe, expect, it } from 'vitest'
import { verdictWhy } from './verdicts'

const buy = {
  verdict: 'buy' as const,
  market: 'US' as const,
  reasons: ['P(beat SPY) 0.64 over 10 trading days', 'expected 2.4% against 3.1% round-trip costs'],
  details: { style: 'swing', horizon_days: 10, exit_by: '2026-10-30', rank: 1, market_picks_enabled: true },
}

describe('verdictWhy', () => {
  it("gives a Buy's style, hold and odds, and its rank among today's picks", () => {
    expect(verdictWhy(buy, 'long')).toBe(
      "Swing · hold ~10 trading days · exit by Oct 30 · 64% to beat SPY · also today's #1 US pick",
    )
    expect(verdictWhy(buy, 'short')).toBe('Swing · ~10 trading days · exit by Oct 30 · 64%')
  })

  it("keeps a TSX Buy's filings note with its reasons", () => {
    const note = 'Price and sector only: TSX stocks have no company filings in this model, so weigh this call accordingly.'
    const tsx = {
      ...buy,
      market: 'TSX' as const,
      reasons: [...buy.reasons, note],
      details: { ...buy.details, rank: undefined, basis: note },
    }
    expect(verdictWhy(tsx, 'long')).toContain(note)
    expect(verdictWhy(tsx, 'short')).not.toContain(note)
  })

  it('says a held Buy is held instead of a rank', () => {
    const held = { ...buy, details: { style: 'position', horizon_days: 63, exit_by: '2027-01-19', held: true } }
    expect(verdictWhy(held, 'long')).toBe('Position · hold ~3 months · exit by Jan 19 · 64% to beat SPY · you hold it')
  })

  it("gives a Hold's or Avoid's reasons, and says when the market's picks are off", () => {
    const hold = {
      verdict: 'hold' as const,
      market: 'TSX' as const,
      reasons: ["doesn't qualify as a buy", 'P(beat XIU.TO) 0.54 is under 0.58 at every horizon'],
      details: { market_picks_enabled: false },
    }
    expect(verdictWhy(hold, 'long')).toBe(
      "doesn't qualify as a buy; P(beat XIU.TO) 0.54 is under 0.58 at every horizon · picks off for TSX this run",
    )
    expect(verdictWhy({ verdict: 'hold', market: null, reasons: ['no crypto model yet'], details: {} }, 'short')).toBe(
      'no crypto model yet',
    )
  })
})
