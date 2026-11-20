import { TriangleAlert } from 'lucide-react'
import { shortDay } from '@/lib/dates'
import {
  basisLine,
  breakevenLine,
  rangeLine,
  sellAtLine,
  statusNote,
  stopFirstLine,
  type Currency,
  type ExitPlan,
} from '@/lib/portfolio/exit-plan'
import type { AssetType } from '@/lib/portfolio/types'

/** Chances are counted on daily closes (R9); stated once per plan that shows one. */
export const CLOSES_LINE = 'Chances count closes at or above the price.'

/** The symbol a forecast plan's drift is measured on: BTC for a coin, XIU.TO on the TSX, else SPY. */
export const planBenchmark = (assetType: AssetType, symbol: string): string =>
  assetType === 'crypto' ? 'BTC' : symbol.endsWith('.TO') ? 'XIU.TO' : 'SPY'

type Line = { text: string; tone?: 'warn' | 'sub' }
/** A plain line, or nothing for a null text. */
const plain = (text: string | null): Line | null => (text === null ? null : { text })

/** The break-even line, in the warning style when getting back to cost is unlikely. */
const breakeven = (plan: ExitPlan, currency: Currency): Line | null => {
  const line = breakevenLine(plan, currency)
  return line && { text: line.text, tone: line.warn ? 'warn' : undefined }
}

const note = (plan: ExitPlan): Line | null => {
  const text = statusNote(plan)
  return text === null ? null : { text, tone: 'sub' }
}

function Lines({ lines }: { lines: (Line | null)[] }) {
  const shown = lines.filter((l): l is Line => l !== null)
  if (shown.length === 0) return null
  return (
    <div className="plan-lines">
      {shown.map((l) =>
        l.tone === 'warn' ? (
          <span key={l.text} className="plan-line warn-cell">
            <TriangleAlert />
            {l.text}
          </span>
        ) : (
          <span key={l.text} className={l.tone === 'sub' ? 'plan-line sub' : 'plan-line'}>
            {l.text}
          </span>
        ),
      )}
    </div>
  )
}

/** Whether the plan's lines show a chance: the sell-at's, stop-first or break-even's. */
export function showsChance(plan: ExitPlan | null): boolean {
  if (plan === null || plan.status === 'fail') return false
  const sellSide = plan.status !== 'range_only' && ((plan.sellAt !== null && plan.pTouch !== null) || plan.pStopFirst !== null)
  return sellSide || (plan.breakeven !== null && plan.pBreakeven !== null)
}

/**
 * A holding's exit plan (exit plan spec §7): the range, sell-at, stop-first, break-even, basis and
 * status lines, in that order, and, when a chance is shown, that chances count closes. `price` is the
 * close the plan was built on. `compact` (the holdings table cell) leaves out a forecast plan's basis
 * and the closes line. A failed plan shows only its note and re-check date; a range-only plan no sell-at.
 */
export function ExitPlanLines({
  plan,
  currency,
  price,
  benchmark,
  compact = false,
}: {
  plan: ExitPlan | null
  currency: Currency
  price: number | null
  benchmark: string
  compact?: boolean
}) {
  if (plan === null) return null
  if (plan.status === 'fail') {
    return <Lines lines={[note(plan), plan.recheckBy === null ? null : { text: `Re-check by ${shortDay(plan.recheckBy)}` }]} />
  }
  const sellAt = plan.status === 'range_only' ? null : sellAtLine(plan, currency)
  const stopFirst = plan.status === 'range_only' ? null : stopFirstLine(plan)
  const even = breakeven(plan, currency)
  const range = rangeLine(plan, currency, price)
  return (
    <Lines
      lines={[
        plain(range),
        plain(sellAt),
        plain(stopFirst),
        even,
        compact && plan.basis === 'forecast' ? null : { text: basisLine(plan, benchmark), tone: 'sub' },
        note(plan),
        !compact && showsChance(plan) ? { text: CLOSES_LINE, tone: 'sub' } : null,
      ]}
    />
  )
}

/** An action card's part of the plan: the range and, under water, the break-even line, with the status note. */
export function ExitPlanCardLines({ plan, currency, price }: { plan: ExitPlan | null; currency: Currency; price: number | null }) {
  if (plan === null) return null
  const range = plan.status === 'fail' ? null : rangeLine(plan, currency, price)
  return <Lines lines={[plain(range), plan.status === 'fail' ? null : breakeven(plan, currency), note(plan)]} />
}

/** The compact cells leave a forecast plan's basis out (R19). */
export const FORECAST_BASIS_NOTE = "Plans are from the model's forecast unless marked “From volatility only”."

/**
 * Under the holdings table, once: the cells leave out the closes line and a forecast plan's basis,
 * so the page says both here (R9, R19). Nothing when no plan there shows a chance.
 */
export function PlanFootnote({ plans }: { plans: readonly (ExitPlan | null)[] }) {
  if (!plans.some(showsChance)) return null
  return (
    <p className="sub" style={{ margin: '10px 0 0', fontSize: 12 }}>
      {CLOSES_LINE} {FORECAST_BASIS_NOTE}
    </p>
  )
}
