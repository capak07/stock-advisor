import { Calendar, TrendingDown, TrendingUp } from 'lucide-react'
import Link from 'next/link'
import { OrderGuide } from '@/components/OrderGuide'
import { RangeBar } from '@/components/picks/RangeBar'
import { catalystsLine, costText, describeFactor, factorBars, holdWords, tfsaNote } from '@/lib/advice'
import type { PickView } from '@/lib/data/picks'
import { shortDay } from '@/lib/dates'
import type { Guide } from '@/lib/guidance'
import { fmtMoney, fmtPct, fmtPrice } from '@/lib/format'
import { RISK_LABELS, type RiskLevel } from '@/lib/portfolio/actions'
import { tickerHref } from '@/lib/ticker'

const pct = (fraction: number) => fmtPct(fraction * 100)

/** Swing: 2 ATR under entry. Position: 3 ATR, but never more than 15% under (pipeline recommend/picks.py). */
const stopRule = (p: PickView) =>
  p.style === 'swing' ? '2 × ATR' : Math.abs(p.stop / p.entry - 0.85) < 1e-6 ? '15% cap' : '3 × ATR'

/**
 * One pick (spec §6.5, restyled per §7.4 and picks_2.html): how it was chosen, its likely range
 * relative to the benchmark, entry, stop and exit-by, the model's backtest, why, and its cost.
 * Never a chance of beating the market (owner decision 2026-11-07).
 */
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
  const currency = p.market === 'US' ? 'USD' : 'CAD'
  const cur = currency === 'USD' ? 'US$' : 'C$'
  // the tiles are narrow three across, so the currency sits in the label: "Entry US$" over "229.50"
  const bare = (price: number) => fmtPrice(price, currency).replace(cur, '')
  const about = [p.name, p.sector].filter(Boolean).join(' · ')
  const bars = factorBars(p.topFactors)
  const [costMain, ...costRest] = p.cost === null ? [] : costText(p.market, p.cost, usdFxFeePct).split(' · ')
  const hasForecast = p.q10 !== null && p.q50 !== null && p.q90 !== null
  const size = `${p.maxPositionPct}%${portfolioCad !== null && portfolioCad > 0 ? ` · ${fmtMoney((portfolioCad * p.maxPositionPct) / 100)}` : ''}`
  return (
    <article className="card card-pad pick" data-symbol={p.symbol}>
      <div className="pick-head">
        <div className="pick-who">
          <span>
            <span className="pick-rank">#{p.rank}</span>{' '}
            <Link href={tickerHref(p.symbol, 'stock')} className="sym" style={{ fontSize: 15 }}>
              {p.symbol}
            </Link>
          </span>
          {about && <span className="name">{about}</span>}
        </div>
        <span className="badge">
          <span className={`dot ${risk.replace('_', '-')}`} />
          {RISK_LABELS[risk] ?? p.riskLevel} risk
        </span>
      </div>
      {p.chosenBy === 'rank' && p.scoreRank != null && p.scoreOf != null ? (
        <div className="pick-chosen">
          <span className="label">Place</span>
          <b className="num">Ranked #{p.scoreRank} of {p.scoreOf} by the model</b>
          <span className="fine" data-rank>
            Chosen by rank: its probabilities run high, so it&apos;s shown by its place in the ranking.
          </span>
          {p.basis && (
            <span className="fine" data-basis>
              {p.basis}
            </span>
          )}
        </div>
      ) : (
        // owner decision 2026-11-07: a pick shows how it was chosen and its backtest, never a P promise
        <div className="pick-chosen">
          <span className="label">Chosen by</span>
          <b>The model&apos;s rule: P(beat) at least 0.58 and an expected return above costs</b>
          <span className="fine" data-rule>
            No chance of beating {p.benchmark} is shown: the backtest below says how its picks did.
          </span>
          {p.basis && (
            <span className="fine" data-basis>
              {p.basis}
            </span>
          )}
        </div>
      )}
      {hasForecast && (
        <div>
          <div className="label">
            Likely {p.horizon}-day return relative to {p.benchmark}
          </div>
          <RangeBar q10={p.q10!} q50={p.q50!} q90={p.q90!} benchmark={p.benchmark} />
          <div className="pick-rlabels num">
            <span className="loss">{pct(p.q10!)}</span>
            <span>mid {pct(p.q50!)}</span>
            <span className="gain">{pct(p.q90!)}</span>
          </div>
        </div>
      )}
      <div className="pick-levels">
        <div className="stat">
          <span className="label">Entry {cur}</span>
          <b>{bare(p.entry)}</b>
        </div>
        <div className="stat">
          <span className="label">Stop {cur}</span>
          <b className="loss">{bare(p.stop)}</b>
          <span className="sub">{stopRule(p)}</span>
        </div>
        <div className="stat" data-exit>
          <span className="label">Exit by</span>
          <b>{shortDay(p.exitBy)}</b>
          <span className="sub">{holdWords(p.horizon)}</span>
        </div>
      </div>
      <p className="fine" data-size>
        Max size {size} · {tfsaNote(p.style)}
      </p>
      {p.trackRecord && (
        <div className="pick-bt">
          <span className="label">The model&apos;s record</span>
          <p data-track>
            Backtest: <b className="num">{p.trackRecord.picks}</b> past picks beat {p.benchmark} by{' '}
            <b className="num">
              {p.trackRecord.meanNetPct >= 0 ? '+' : '−'}
              {Math.abs(p.trackRecord.meanNetPct).toFixed(1)}%
            </b>{' '}
            each after costs, and beat it before costs <b className="num">{Math.round(p.trackRecord.beatRate * 100)}%</b> of the
            time.
          </p>
        </div>
      )}
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
      <p className="fine">
        {p.catalysts.length > 0 && <Calendar className="pick-cal" />}
        {catalystsLine(p.catalysts)}
      </p>
      {guide && <OrderGuide plan={guide.plan} caption={guide.caption} />}
      <div className="pick-foot">
        {costMain ? (
          <span className="fine num" data-cost title="Estimated cost">
            {costMain} <span>{costRest.join(' · ')}</span>
          </span>
        ) : (
          <span />
        )}
        {action}
      </div>
    </article>
  )
}
