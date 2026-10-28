import { Calendar, TrendingDown, TrendingUp } from 'lucide-react'
import Link from 'next/link'
import { OrderGuide } from '@/components/OrderGuide'
import { RangeBar } from '@/components/picks/RangeBar'
import { catalystsLine, costText, describeFactor, factorBars, holdText, tfsaNote } from '@/lib/advice'
import type { PickView } from '@/lib/data/picks'
import type { Guide } from '@/lib/guidance'
import { fmtMoney, fmtPct, fmtPrice } from '@/lib/format'
import { RISK_LABELS, type RiskLevel } from '@/lib/portfolio/actions'
import { tickerHref } from '@/lib/ticker'

const pct = (fraction: number) => fmtPct(fraction * 100)

/** Swing: 2 ATR under entry. Position: 3 ATR, but never more than 15% under (pipeline recommend/picks.py). */
const stopRule = (p: PickView) =>
  p.style === 'swing' ? '2 × ATR' : Math.abs(p.stop / p.entry - 0.85) < 1e-6 ? '15% cap' : '3 × ATR'

/** One pick (spec §6.5): its likely range relative to the benchmark, odds, hold, stop, size, cost and why. */
export function PickCard({
  pick,
  portfolioCad,
  usdFxFeePct,
  guide = null,
  action,
}: {
  pick: PickView
  /** The portfolio's total CAD value, for the max size in dollars; null when there's nothing held. */
  portfolioCad: number | null
  usdFxFeePct: number
  /** How to place the buy; null without the rate a US pick needs. */
  guide?: Guide | null
  action?: React.ReactNode
}) {
  const p = pick
  const risk = p.riskLevel as RiskLevel
  const about = [p.name, p.sector].filter(Boolean).join(' · ')
  const bars = factorBars(p.topFactors)
  const [costMain, ...costRest] = p.cost === null ? [] : costText(p.market, p.cost, usdFxFeePct).split(' · ')
  const hasForecast = p.q10 !== null && p.q50 !== null && p.q90 !== null
  return (
    <article className="card pick" data-symbol={p.symbol}>
      <div className="pick-head">
        <div>
          <span className="pick-rank">#{p.rank}</span>{' '}
          <Link href={tickerHref(p.symbol, 'stock')} className="sym" style={{ fontSize: 15 }}>
            {p.symbol}
          </Link>
          {about && <div className="sub">{about}</div>}
        </div>
        <span className="badge">
          <span className={`dot ${risk.replace('_', '-')}`} />
          {RISK_LABELS[risk] ?? p.riskLevel} risk
        </span>
      </div>
      {hasForecast && (
        <div>
          <div className="flex justify-between num" style={{ fontSize: 12 }}>
            <span className="loss">q10 {pct(p.q10!)}</span>
            <span>q50 {pct(p.q50!)}</span>
            <span className="gain">q90 {pct(p.q90!)}</span>
          </div>
          <RangeBar q10={p.q10!} q50={p.q50!} q90={p.q90!} benchmark={p.benchmark} />
          <div className="sub">
            Likely {p.horizon}-day return relative to {p.benchmark}
          </div>
        </div>
      )}
      <dl className="pick-facts">
        {p.pBeat !== null && (
          <div>
            <dt>Beats {p.benchmark}</dt>
            <dd className="num" style={{ fontWeight: 600 }}>
              {Math.round(p.pBeat * 100)}%
            </dd>
          </div>
        )}
        <div>
          <dt>Hold</dt>
          <dd>{holdText(p.horizon, p.exitBy)}</dd>
        </div>
        <div>
          <dt>Stop</dt>
          <dd className="num">
            {fmtPrice(p.stop, p.market === 'US' ? 'USD' : 'CAD')} <span className="sub">{stopRule(p)}</span>
          </dd>
        </div>
        <div>
          <dt>Max size</dt>
          <dd className="num">
            {p.maxPositionPct}%{portfolioCad !== null && portfolioCad > 0 && ` · ${fmtMoney((portfolioCad * p.maxPositionPct) / 100)}`}
          </dd>
        </div>
        {costMain && (
          <div style={{ gridColumn: '1 / 3' }}>
            <dt>Est. cost</dt>
            <dd className="num">
              {costMain} <span className="sub">{costRest.join(' · ')}</span>
            </dd>
          </div>
        )}
      </dl>
      {p.topFactors.length > 0 && (
        <ul className="pick-why">
          {p.topFactors.map((f, i) => (
            <li key={f.feature}>
              {bars[i].up ? <TrendingUp className="gain" /> : <TrendingDown className="loss" />}
              {describeFactor(f.feature, f.value, p.benchmark)}
            </li>
          ))}
        </ul>
      )}
      <p className="sub" style={{ margin: 0 }}>
        {p.catalysts.length > 0 && <Calendar className="pick-cal" />}
        {catalystsLine(p.catalysts)}
      </p>
      {guide && <OrderGuide plan={guide.plan} caption={guide.caption} />}
      <div className="pick-foot">
        <span className="sub">{tfsaNote(p.style)}</span>
        {action}
      </div>
    </article>
  )
}
