import { describe, expect, it } from 'vitest'
import {
  assetCurrency,
  basisLine,
  breakevenLine,
  parseExitPlan,
  rangeLine,
  sellAtLine,
  statusNote,
  stopFirstLine,
  type ExitPlan,
} from './exit-plan'

const plan = (over: Partial<ExitPlan> = {}): ExitPlan => ({
  status: 'pass',
  basis: 'volatility',
  horizon: 21,
  recheckBy: '2026-12-19',
  low: 4.2,
  mid: 5.05,
  high: 6.1,
  sellAt: 5.6,
  pTouch: 0.33,
  pStopFirst: 0.22,
  pUp: 0.55,
  breakeven: 1.9,
  pBreakeven: 0.06,
  drift: null,
  costPrice: 4.75,
  ...over,
})

const nothing: Partial<ExitPlan> = {
  low: null,
  mid: null,
  high: null,
  sellAt: null,
  pTouch: null,
  pStopFirst: null,
  pUp: null,
  breakeven: null,
  pBreakeven: null,
  costPrice: null,
}

describe('parseExitPlan', () => {
  it('is null for null, a non-object and an empty object', () => {
    expect(parseExitPlan(null)).toBeNull()
    expect(parseExitPlan(undefined)).toBeNull()
    expect(parseExitPlan('plan')).toBeNull()
    expect(parseExitPlan([])).toBeNull()
    expect(parseExitPlan({})).toBeNull()
  })

  it('reads the stored snake_case keys and converts numeric strings', () => {
    const parsed = parseExitPlan({
      version: 1,
      basis: 'forecast',
      status: 'unvalidated',
      horizon: 21,
      recheck_by: '2026-12-19',
      low: '4.2',
      mid: 5.05,
      high: 6.1,
      sell_at: '5.6',
      p_touch: 0.33,
      p_stop_first: 0.22,
      p_up: 0.55,
      breakeven: 1.9,
      p_breakeven: 0.06,
      cost_price: '4.75',
      drift: 0.009,
    })
    expect(parsed).toEqual({
      status: 'unvalidated',
      basis: 'forecast',
      horizon: 21,
      recheckBy: '2026-12-19',
      low: 4.2,
      mid: 5.05,
      high: 6.1,
      sellAt: 5.6,
      pTouch: 0.33,
      pStopFirst: 0.22,
      pUp: 0.55,
      breakeven: 1.9,
      pBreakeven: 0.06,
      drift: 0.009,
      costPrice: 4.75,
    })
  })

  it('turns missing, null and non-finite numbers into null', () => {
    const parsed = parseExitPlan({
      basis: 'volatility',
      status: 'fail',
      horizon: 21,
      recheck_by: null,
      low: null,
      mid: 'abc',
      high: Infinity,
    })
    expect(parsed).toMatchObject({ recheckBy: null, low: null, mid: null, high: null, sellAt: null, costPrice: null, drift: null })
  })

  it('is null for an unknown status or basis, or a horizon that is not a positive number', () => {
    const good = { basis: 'volatility', status: 'pass', horizon: 21 }
    expect(parseExitPlan(good)).not.toBeNull()
    expect(parseExitPlan({ ...good, status: 'bad' })).toBeNull()
    expect(parseExitPlan({ ...good, basis: 'magic' })).toBeNull()
    expect(parseExitPlan({ ...good, horizon: 0 })).toBeNull()
    expect(parseExitPlan({ ...good, horizon: -3 })).toBeNull()
    expect(parseExitPlan({ ...good, horizon: 'soon' })).toBeNull()
    expect(parseExitPlan({ ...good, horizon: null })).toBeNull()
  })
})

describe('assetCurrency', () => {
  it('is CAD for a TSX stock and USD otherwise', () => {
    expect(assetCurrency('stock', 'ABC.TO')).toBe('CAD')
    expect(assetCurrency('stock', 'ABC')).toBe('USD')
    expect(assetCurrency('crypto', 'BTC')).toBe('USD')
    expect(assetCurrency('crypto', 'X.TO')).toBe('USD')
  })
})

describe('rangeLine', () => {
  it('shows the range by the re-check date, with the middle against the price', () => {
    expect(rangeLine(plan(), 'USD', 4.85)).toBe('Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)')
  })

  it('says the days when there is no re-check date, and drops the percent without a price', () => {
    expect(rangeLine(plan({ recheckBy: null }), 'USD', 4.85)).toBe('Range in 21 days: US$4.20 – 5.05 – 6.10 (+4%)')
    expect(rangeLine(plan(), 'CAD', null)).toBe('Range by Dec 19: C$4.20 – 5.05 – 6.10')
  })

  it('shows a fall with a real minus sign', () => {
    expect(rangeLine(plan(), 'USD', 6)).toBe('Range by Dec 19: US$4.20 – 5.05 – 6.10 (−16%)')
  })

  it('is null when any of the three numbers is null', () => {
    expect(rangeLine(plan({ low: null }), 'USD', 4.85)).toBeNull()
    expect(rangeLine(plan({ mid: null }), 'USD', 4.85)).toBeNull()
    expect(rangeLine(plan({ high: null }), 'USD', 4.85)).toBeNull()
    expect(rangeLine(plan(nothing), 'USD', 4.85)).toBeNull()
  })
})

describe('sellAtLine', () => {
  it('shows the price, the chance and the gain on cost', () => {
    expect(sellAtLine(plan(), 'USD')).toBe('Sell at US$5.60 · about 1 in 3 · +18% on cost')
  })

  it('says "reached in N% of cases" outside 0.30 to 0.37', () => {
    expect(sellAtLine(plan({ pTouch: 0.45 }), 'USD')).toBe('Sell at US$5.60 · reached in 45% of cases · +18% on cost')
    expect(sellAtLine(plan({ pTouch: 0.29 }), 'USD')).toBe('Sell at US$5.60 · reached in 29% of cases · +18% on cost')
    expect(sellAtLine(plan({ pTouch: 0.3 }), 'USD')).toContain('about 1 in 3')
    expect(sellAtLine(plan({ pTouch: 0.37 }), 'USD')).toContain('about 1 in 3')
  })

  it('drops the cost part without a cost price, and the chance without one', () => {
    expect(sellAtLine(plan({ costPrice: null }), 'USD')).toBe('Sell at US$5.60 · about 1 in 3')
    expect(sellAtLine(plan({ pTouch: null }), 'CAD')).toBe('Sell at C$5.60 · +18% on cost')
  })

  it('is null without a sell-at price', () => {
    expect(sellAtLine(plan({ sellAt: null }), 'USD')).toBeNull()
  })
})

describe('stopFirstLine', () => {
  it('shows the chance', () => {
    expect(stopFirstLine(plan())).toBe('Stop first: 22%')
  })
  it('is null without the chance', () => {
    expect(stopFirstLine(plan({ pStopFirst: null }))).toBeNull()
  })
})

describe('breakevenLine', () => {
  it('shows the price and the chance', () => {
    expect(breakevenLine(plan({ pBreakeven: 0.4 }), 'USD')).toEqual({
      text: 'Break-even US$1.90 · reached in 40% of cases',
      warn: false,
    })
  })

  it('does not warn at 0.25 or more', () => {
    expect(breakevenLine(plan({ pBreakeven: 0.25 }), 'USD')).toEqual({
      text: 'Break-even US$1.90 · reached in 25% of cases',
      warn: false,
    })
  })

  it('warns in words under 0.25 when it can name the date', () => {
    const line = breakevenLine(plan({ pBreakeven: 0.06 }), 'USD')
    expect(line?.warn).toBe(true)
    expect(line?.text).toBe(
      "Unlikely to get back to your cost by Dec 19: reached in 6% of cases. Your cost doesn't change where it goes next.",
    )
  })

  it('says the days without a re-check date', () => {
    expect(breakevenLine(plan({ recheckBy: null }), 'USD')?.text).toBe(
      "Unlikely to get back to your cost in 21 days: reached in 6% of cases. Your cost doesn't change where it goes next.",
    )
  })

  it('shows only the price without a chance, and is null without a price', () => {
    expect(breakevenLine(plan({ pBreakeven: null }), 'USD')).toEqual({ text: 'Break-even US$1.90', warn: false })
    expect(breakevenLine(plan({ breakeven: null }), 'USD')).toBeNull()
  })
})

describe('basisLine', () => {
  it('names a volatility-only plan', () => {
    expect(basisLine(plan(), 'SPY')).toBe('From volatility only — no view on direction')
  })

  it("names the forecast and the benchmark's drift", () => {
    expect(basisLine(plan({ basis: 'forecast', drift: 0.009 }), 'SPY')).toBe(
      "From the model's forecast · assumes SPY drifts +0.9% over 21 days",
    )
  })

  it('drops the drift part when there is none', () => {
    expect(basisLine(plan({ basis: 'forecast', drift: null }), 'SPY')).toBe("From the model's forecast")
  })
})

describe('statusNote', () => {
  it('has a note for each status but pass', () => {
    expect(statusNote(plan({ status: 'unvalidated' }))).toBe(
      'Not validated yet: the first benchmark run after this change checks these chances.',
    )
    expect(statusNote(plan({ status: 'range_only' }))).toBe('The sell-at price is hidden: it missed the benchmark check.')
    expect(statusNote(plan({ status: 'fail' }))).toBe('The exit plan is hidden: its range missed the benchmark check.')
    expect(statusNote(plan({ status: 'pass' }))).toBeNull()
  })

  it('an unvalidated plan with numbers yields its lines and the note (R17)', () => {
    const p = plan({ status: 'unvalidated' })
    expect(rangeLine(p, 'USD', 4.85)).not.toBeNull()
    expect(sellAtLine(p, 'USD')).not.toBeNull()
    expect(stopFirstLine(p)).not.toBeNull()
    expect(breakevenLine(p, 'USD')).not.toBeNull()
    expect(statusNote(p)).toMatch(/^Not validated yet/)
  })
})
