import Link from 'next/link'
import { fmtMoney, fmtPct } from '@/lib/format'
import { priceDirection } from '@/lib/motion'
import { dayMove, type Period, type PeriodReturns } from '@/lib/portfolio/returns'
import type { Totals } from '@/lib/portfolio/valuation'
import { moveWhen } from '@/lib/today'

const tone = (value: number) => (value < 0 ? 'loss' : 'gain')

/**
 * Today's portfolio card, a link to My Portfolio: only the money made or lost today and its percent (owner request
 * 2026-11-23; the total, the return since the first buy, the gap to SPY and the chart are on My Portfolio). "Today"
 * is the last session's move, named by its weekday when that isn't today: a weekend, a holiday, or before the open
 * and before a Refresh brings live prices. An empty portfolio shows C$0.00.
 */
export function PortfolioSummary({
  totals,
  periods,
  accounts,
  holdings,
  today,
}: {
  totals: Totals
  periods: Record<Period, PeriodReturns> | null
  /** Accounts with an open position, as labels. */
  accounts: string[]
  /** How many holdings are open. */
  holdings: number
  /** Today in Toronto (`YYYY-MM-DD`): the move reads "today" only when the 1D period ends on it. */
  today: string
}) {
  const move = holdings > 0 ? dayMove(totals.valueCad, periods) : null

  return (
    <Link className="card hero rim lift today-hero enter" href="/portfolio" aria-label="Portfolio summary">
      <div className="label">Today{accounts.length > 0 && ` · ${accounts.join(' and ')}`}</div>
      {holdings === 0 ? (
        <>
          <div className="big num" style={{ margin: '8px 0 6px' }} data-testid="today-value">
            {fmtMoney(0, { digits: 2 })}
          </div>
          <p className="sub" style={{ margin: 0, fontSize: 13 }}>
            No holdings yet. Add your first buy on My Portfolio.
          </p>
        </>
      ) : move ? (
        <>
          <div className={`big num ${tone(move.cad)}`} data-testid="today-value" data-price={priceDirection(move.pct)} style={{ margin: '8px 0 6px' }}>
            {fmtMoney(move.cad, { digits: 2, signed: true })}
          </div>
          <div className={`num ${tone(move.pct)}`} style={{ fontSize: 14 }}>
            {fmtPct(move.pct)} {moveWhen(periods?.['1d'].days.at(-1), today)}
          </div>
        </>
      ) : (
        <>
          <div className="big num" style={{ margin: '8px 0 6px' }} data-testid="today-value">
            —
          </div>
          <p className="sub" style={{ margin: 0, fontSize: 13 }}>
            No prices to compare yet.
          </p>
        </>
      )}
    </Link>
  )
}
