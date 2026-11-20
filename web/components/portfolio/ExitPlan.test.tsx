import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ExitPlan } from '@/lib/portfolio/exit-plan'
import { ExitPlanCardLines, ExitPlanLines, ExitPlanWithAlert, PlanFootnote } from './ExitPlan'

const plan = (over: Partial<ExitPlan> = {}): ExitPlan => ({
  assetType: 'stock',
  status: 'pass',
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
  breakeven: null,
  pBreakeven: null,
  drift: 0.009,
  costPrice: 4.75,
  ...over,
})

const CLOSES = 'Chances count closes at or above the price.'
const UNVALIDATED = 'Not validated yet: the first benchmark run after this change checks these chances.'

/** Each rendered line's text, in order (a line holds no nested span; a warning line starts with its icon). */
const lines = (node: ReactElement): string[] =>
  [...renderToStaticMarkup(node).matchAll(/<span class="plan-line[^"]*">(.*?)<\/span>/g)].map((m) =>
    m[1]
      .replace(/<svg.*?<\/svg>/g, '')
      .replaceAll('&#x27;', "'")
      .replaceAll('&amp;', '&'),
  )
const html = (node: ReactElement) => renderToStaticMarkup(node).replaceAll('&#x27;', "'")

describe('ExitPlanLines', () => {
  it('renders a forecast plan as the range, sell-at, stop-first and basis lines, then the closes line, with no status note', () => {
    expect(lines(<ExitPlanLines action="hold" plan={plan()} currency="USD" price={4.85} benchmark="SPY" />)).toEqual([
      'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
      'Sell at US$5.60 · about 1 in 3 · +18% on cost',
      'Stop first: 22%',
      "From the model's forecast · assumes SPY drifts +0.9% over 21 trading days",
      CLOSES,
    ])
  })

  it('takes "+N% on cost" from the plan\'s own cost price', () => {
    const text = html(<ExitPlanLines action="hold" plan={plan({ costPrice: 5 })} currency="USD" price={4.85} benchmark="SPY" />)
    expect(text).toContain('Sell at US$5.60 · about 1 in 3 · +12% on cost')
  })

  it('shows an unvalidated plan\'s numbers together with the "Not validated yet" note', () => {
    expect(lines(<ExitPlanLines action="hold" plan={plan({ status: 'unvalidated' })} currency="USD" price={4.85} benchmark="SPY" />)).toEqual([
      'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
      'Sell at US$5.60 · about 1 in 3 · +18% on cost',
      'Stop first: 22%',
      "From the model's forecast · assumes SPY drifts +0.9% over 21 trading days",
      UNVALIDATED,
      CLOSES,
    ])
    // the table cell too
    const cell = lines(<ExitPlanLines action="hold" plan={plan({ status: 'unvalidated' })} currency="USD" price={4.85} benchmark="SPY" compact />)
    expect(cell[0]).toBe('Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)')
    expect(cell).toContain(UNVALIDATED)
  })

  it('has no sell-at line for a range-only plan, and says why', () => {
    const shown = lines(
      <ExitPlanLines action="hold" plan={plan({ status: 'range_only', sellAt: null, pTouch: null, pStopFirst: null })} currency="USD" price={4.85} benchmark="SPY" />,
    )
    expect(shown.some((l) => l.startsWith('Sell at'))).toBe(false)
    expect(shown).toContain('The sell-at price is hidden: it missed the benchmark check.')
    expect(shown[0]).toMatch(/^Range by Dec 19/)
  })

  it('renders a failed plan as its note and the re-check date alone', () => {
    const failed = plan({
      status: 'fail',
      low: null,
      mid: null,
      high: null,
      sellAt: null,
      pTouch: null,
      pStopFirst: null,
      pUp: null,
      costPrice: null,
      drift: null,
    })
    expect(lines(<ExitPlanLines action="hold" plan={failed} currency="USD" price={4.85} benchmark="SPY" />)).toEqual([
      'The exit plan is hidden: its range missed the benchmark check.',
      'Re-check by Dec 19',
    ])
  })

  it('shows an unlikely break-even in the warning style', () => {
    const under = plan({ basis: 'volatility', drift: null, breakeven: 1.9, pBreakeven: 0.06, sellAt: null, pTouch: null, pStopFirst: null })
    const text = html(<ExitPlanLines action="hold" plan={under} currency="USD" price={1.2} benchmark="SPY" />)
    expect(text).toMatch(/<span class="plan-line warn-cell"><svg/)
    expect(text).toContain(
      "Unlikely to get back to your cost by Dec 19: reached in 6% of cases. Your cost doesn't change where it goes next.",
    )
    const likely = html(<ExitPlanLines action="hold" plan={{ ...under, pBreakeven: 0.4 }} currency="USD" price={1.2} benchmark="SPY" />)
    expect(likely).not.toContain('warn-cell')
    expect(likely).toContain('Break-even US$1.90 · reached in 40% of cases')
  })

  it('leaves the closes line and the forecast basis out of the compact cell, keeping "From volatility only"', () => {
    const forecast = lines(<ExitPlanLines action="hold" plan={plan()} currency="USD" price={4.85} benchmark="SPY" compact />)
    expect(forecast).toEqual([
      'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
      'Sell at US$5.60 · about 1 in 3 · +18% on cost',
      'Stop first: 22%',
    ])
    const vol = lines(<ExitPlanLines action="hold" plan={plan({ basis: 'volatility', drift: null })} currency="USD" price={4.85} benchmark="SPY" compact />)
    expect(vol.at(-1)).toBe('From volatility only — no view on direction')
    expect(vol).not.toContain(CLOSES)
  })

  it('has no closes line when the plan shows no chance', () => {
    const rangeOnly = plan({ status: 'range_only', sellAt: null, pTouch: null, pStopFirst: null })
    expect(lines(<ExitPlanLines action="hold" plan={rangeOnly} currency="USD" price={4.85} benchmark="SPY" />)).not.toContain(CLOSES)
  })

  it('renders nothing without a plan', () => {
    expect(renderToStaticMarkup(<ExitPlanLines action="hold" plan={null} currency="USD" price={4.85} benchmark="SPY" />)).toBe('')
  })

  it('prices a TSX plan in C$', () => {
    expect(lines(<ExitPlanLines action="hold" plan={plan()} currency="CAD" price={4.85} benchmark="XIU.TO" compact />)[0]).toBe(
      'Range by Dec 19: C$4.20 – 5.05 – 6.10 (+4%)',
    )
  })
})

describe('ExitPlanCardLines', () => {
  it('shows the range and, under water, the break-even line, with the status note', () => {
    const under = plan({ status: 'unvalidated', breakeven: 6, pBreakeven: 0.3 })
    expect(lines(<ExitPlanCardLines plan={under} currency="USD" price={4.85} />)).toEqual([
      'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
      'Break-even US$6.00 · reached in 30% of cases',
      UNVALIDATED,
    ])
    expect(lines(<ExitPlanCardLines plan={plan()} currency="USD" price={4.85} />)).toEqual([
      'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
    ])
  })

  it('renders nothing without a plan', () => {
    expect(renderToStaticMarkup(<ExitPlanCardLines plan={null} currency="USD" price={4.85} />)).toBe('')
  })
})

describe('PlanFootnote', () => {
  it('says once under the table that chances count closes and which plans are from the forecast', () => {
    expect(html(<PlanFootnote plans={[null, { plan: plan(), action: 'hold' }]} />)).toContain(
      "Chances count closes at or above the price. Plans are from the model's forecast unless marked “From volatility only”.",
    )
  })

  it('is left out when no plan shows a chance', () => {
    const rangeOnly = plan({ status: 'range_only', sellAt: null, pTouch: null, pStopFirst: null })
    expect(renderToStaticMarkup(<PlanFootnote plans={[null, { plan: rangeOnly, action: 'hold' }]} />)).toBe('')
  })

  it("is left out when the only chance shown would be a Sell's or a Trim's sell-at", () => {
    const sellSide = plan({ breakeven: null, pBreakeven: null })
    expect(renderToStaticMarkup(<PlanFootnote plans={[{ plan: sellSide, action: 'sell' }, { plan: sellSide, action: 'trim' }]} />)).toBe('')
    expect(html(<PlanFootnote plans={[{ plan: sellSide, action: 'add' }]} />)).toContain(CLOSES)
  })
})

/** A Sell's or a Trim's plan with every number: under water, so it has a break-even line too. */
const full = plan({ status: 'unvalidated', breakeven: 6, pBreakeven: 0.3 })
const alertLink = /<a [^>]*class="text-link plan-alert"[^>]*>Alert me at/
const props = { symbol: 'ABC', assetType: 'stock' as const, currency: 'USD' as const, price: 4.85, benchmark: 'SPY' }

describe('a Sell or a Trim shows no sell-at price (R20a)', () => {
  for (const action of ['sell', 'trim'] as const) {
    it(`a ${action} keeps the range and break-even in the cell, with no sell-at, stop-first or alert`, () => {
      const cell = <ExitPlanWithAlert plan={full} action={action} {...props} compact />
      expect(lines(cell)).toEqual([
        'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
        'Break-even US$6.00 · reached in 30% of cases',
        UNVALIDATED,
      ])
      expect(html(cell)).not.toMatch(alertLink)
    })

    it(`a ${action} keeps the range and break-even on the ticker page's card, with no sell-at, stop-first or alert`, () => {
      const card = <ExitPlanWithAlert plan={full} action={action} {...props} />
      expect(lines(card)).toEqual([
        'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
        'Break-even US$6.00 · reached in 30% of cases',
        "From the model's forecast · assumes SPY drifts +0.9% over 21 trading days",
        UNVALIDATED,
        CLOSES,
      ])
      expect(html(card)).not.toMatch(alertLink)
    })

    it(`a ${action}'s action card keeps the range and break-even, with no sell-at or stop-first`, () => {
      expect(lines(<ExitPlanCardLines plan={full} currency="USD" price={4.85} />)).toEqual([
        'Range by Dec 19: US$4.20 – 5.05 – 6.10 (+4%)',
        'Break-even US$6.00 · reached in 30% of cases',
        UNVALIDATED,
      ])
    })
  }

  it('a Hold or an Add with the same plan shows the sell-at, stop-first and the alert link', () => {
    for (const action of ['hold', 'add'] as const) {
      const cell = <ExitPlanWithAlert plan={full} action={action} {...props} compact />
      expect(lines(cell)).toContain('Sell at US$5.60 · about 1 in 3 · +18% on cost')
      expect(lines(cell)).toContain('Stop first: 22%')
      expect(html(cell)).toMatch(alertLink)
      expect(html(cell)).toContain('href="/ticker/ABC?alertLevel=5.6&amp;alertDir=above&amp;alertNote=exit+plan+sell-at#alerts"')
    }
  })

  it('a range-only or failed plan has no alert link on a Hold', () => {
    const rangeOnly = plan({ status: 'range_only', sellAt: null, pTouch: null, pStopFirst: null })
    expect(html(<ExitPlanWithAlert plan={rangeOnly} action="hold" {...props} />)).not.toMatch(alertLink)
    expect(html(<ExitPlanWithAlert plan={{ ...plan(), status: 'range_only' }} action="hold" {...props} />)).not.toMatch(alertLink)
  })
})
