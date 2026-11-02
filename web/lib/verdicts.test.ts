import { describe, expect, it } from 'vitest'
import { heldCalls, type HeldActionLike, verdictWhy } from './verdicts'

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

const action = (over: Partial<HeldActionLike>): HeldActionLike => ({
  account: 'tfsa',
  symbol: 'XRPN',
  assetType: 'stock',
  action: 'hold',
  review: false,
  reasons: ['no rule fired'],
  horizonDays: null,
  exitBy: null,
  ...over,
})

describe('heldCalls', () => {
  it("gives a held symbol My Portfolio's action and its card sentence", () => {
    const calls = heldCalls([action({ action: 'sell', reasons: ['closed at 14.71, under its trailing stop 31.35'] })])
    expect(calls.get('stock:XRPN')).toEqual({
      group: 'sell',
      label: 'Sell',
      why: 'You hold it · Closed at 14.71, under its trailing stop 31.35',
    })
  })

  it('takes the most urgent action across accounts and says the others differ', () => {
    const calls = heldCalls([
      action({ account: 'tfsa', action: 'hold', horizonDays: 21, exitBy: '2026-11-30', reasons: ['no rule fired'] }),
      action({ account: 'non_registered', action: 'trim', reasons: ['up 40% and its 21-day momentum is at the 12th percentile'] }),
    ])
    expect(calls.get('stock:XRPN')).toEqual({
      group: 'trim',
      label: 'Trim',
      why: 'You hold it · Up 40% and its 21-day momentum is at the 12th percentile · other accounts differ, see Portfolio',
    })
  })

  it('says nothing about other accounts when they agree', () => {
    const sell = { action: 'sell' as const, reasons: ['P(beat SPY) 0.40 over 21 trading days'] }
    const calls = heldCalls([action({ account: 'tfsa', ...sell }), action({ account: 'rrsp', ...sell })])
    expect(calls.get('stock:XRPN')?.why).toBe('You hold it · P(beat SPY) 0.40 over 21 trading days')
  })

  it('shows a flagged Hold as Review with its review reasons, and a plain Hold with its hold', () => {
    const calls = heldCalls([
      action({ symbol: 'KEEL.TO', review: true, reasons: ['no rule fired', 'earnings on Nov 5'] }),
      action({ symbol: 'VEEA', horizonDays: 21, exitBy: '2026-11-30' }),
    ])
    expect(calls.get('stock:KEEL.TO')).toEqual({ group: 'review', label: 'Review', why: 'You hold it · Earnings on Nov 5' })
    expect(calls.get('stock:VEEA')).toEqual({ group: 'hold', label: 'Hold', why: 'You hold it · hold ~21 days · exit by Nov 30' })
  })

  it('keeps a coin and a stock with the same ticker apart', () => {
    const calls = heldCalls([
      action({ symbol: 'LINK', assetType: 'crypto', action: 'sell', reasons: ['closed at 9.10, under its trailing stop 10.00'] }),
    ])
    expect(calls.get('crypto:LINK')?.label).toBe('Sell')
    expect(calls.has('stock:LINK')).toBe(false)
  })
})
