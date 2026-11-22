import Link from 'next/link'
import { Sparkline } from '@/components/Sparkline'
import { fmtMoney, fmtPct } from '@/lib/format'
import { priceDirection } from '@/lib/motion'
import { dayMove, type Period, type PeriodReturns } from '@/lib/portfolio/returns'
import type { Totals } from '@/lib/portfolio/valuation'
import { moveWhen } from '@/lib/today'

const last = (values: readonly number[] | null | undefined): number | null =>
  values && values.length > 0 ? values[values.length - 1] : null

/** 252 trading days back takes 253 closes; fewer means the "1Y" view starts at the first buy. */
const YEAR_POINTS = 253

/** "+2.1 pts", "−1.0 pts" */
const pts = (value: number) => fmtPct(value).replace('%', ' pts')

const tone = (value: number) => (value < 0 ? 'loss' : 'gain')

/**
 * Today's portfolio card (spec §7.1), a link to My Portfolio: the total value, today's change (the last
 * session's, named by its weekday on a weekend or holiday), the return since the first buy, the gap to
 * SPY over a year, and three months against SPY in CAD. No cash figure: the app keeps no cash balance.
 * An empty portfolio shows C$0.00 and no chart.
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
  /** Today in Toronto (`YYYY-MM-DD`): the day move reads "today" only when the 1D period ends on it. */
  today: string
}) {
  const move = dayMove(totals.valueCad, periods)
  const allPct = last(periods?.all.portfolio) ?? (totals.costCad > 0 ? (totals.gainCad / totals.costCad) * 100 : null)
  const year = periods?.['12m'] ?? null
  const yearPortfolio = last(year?.portfolio)
  const yearSpy = last(year?.spy)
  const vsSpy = yearPortfolio !== null && yearSpy !== null ? yearPortfolio - yearSpy : null
  const quarter = periods?.['3m'] ?? null

  return (
    <Link className="card hero rim lift today-hero enter" href="/portfolio" aria-label="Portfolio summary">
      <div className="hero-grid">
        <div>
          <div className="label">Portfolio{accounts.length > 0 && ` · ${accounts.join(' and ')}`}</div>
          <div className="big num" style={{ margin: '8px 0 6px' }} data-testid="today-value" data-price={priceDirection(move?.pct)}>
            {fmtMoney(totals.valueCad, { digits: 2 })}
          </div>
          {holdings === 0 ? (
            <p className="sub" style={{ margin: 0, fontSize: 13 }}>
              No holdings yet. Add your first buy on My Portfolio.
            </p>
          ) : (
            <>
              {move && (
                <div className={`num ${tone(move.pct)}`} style={{ fontSize: 14 }}>
                  {fmtMoney(move.cad, { digits: 2, signed: true })} ({fmtPct(move.pct)}) {moveWhen(periods?.['1d'].days.at(-1), today)}
                </div>
              )}
              <div className="hero-meta">
                {allPct !== null && (
                  <div>
                    <div className="label">All time</div>
                    <div className={`num ${tone(allPct)}`} style={{ marginTop: 3 }}>
                      {fmtPct(allPct)}
                    </div>
                  </div>
                )}
                {vsSpy !== null && year && (
                  <div>
                    <div className="label">vs SPY, {year.days.length >= YEAR_POINTS ? '1Y' : 'since first buy'}</div>
                    <div className="num" style={{ marginTop: 3 }}>
                      {pts(vsSpy)}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
        {holdings > 0 && quarter && (
          <Sparkline
            values={quarter.portfolio}
            compare={quarter.spy ?? undefined}
            label="Portfolio over 3 months against SPY in CAD"
          />
        )}
      </div>
    </Link>
  )
}
