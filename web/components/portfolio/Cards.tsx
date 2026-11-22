import { Info, Sparkles, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import type { CSSProperties } from 'react'
import { shortDay } from '@/lib/dates'
import { LowRankChip } from '@/components/LowRankChip'
import { OrderGuide } from '@/components/OrderGuide'
import { fmtMoney, fmtPct, fmtPrice, fmtQty } from '@/lib/format'
import { joinPlans } from '@/lib/guidance'
import type { OrderPlan } from '@/lib/orders'
import {
  ACTION_LABELS,
  RISK_LABELS,
  actionGroup,
  actionGroups,
  cardReason,
  holdText,
  type HoldingAction,
} from '@/lib/portfolio/actions'
import { assetCurrency, statusNote } from '@/lib/portfolio/exit-plan'
import { positionKey } from '@/lib/portfolio/ledger'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import { NOT_RATED, type Slice } from '@/lib/portfolio/valuation'
import type { HoldingRow } from '@/lib/portfolio/view'
import type { Warning } from '@/lib/portfolio/warnings'
import { tickerHref } from '@/lib/ticker'
import { moveWhen } from '@/lib/today'
import { ExitPlanCardLines, ExitPlanWithAlert, PlanFootnote, planBenchmark } from './ExitPlan'
import { HoldList } from './HoldList'

/** A holding with its latest run action. */
type Acted = HoldingRow & { action: HoldingAction }

/** Each acted holding's order for its action and the stop to keep (or, without a stop, its sell-at limit sell), by position key. */
export type HoldingGuides = Map<string, { order: OrderPlan | null; stop: OrderPlan | null }>

const acted = (holdings: readonly HoldingRow[]): Acted[] => holdings.filter((h): h is Acted => h.action !== null)

/** Sell → Trim → Review → Add cards from the latest run's actions, then the plain Holds folded (spec §7.2, §7.3). */
export function ActionsCard({
  holdings,
  asOf,
  guides,
  lowRanks = new Map(),
}: {
  holdings: HoldingRow[]
  asOf: string | null
  guides: HoldingGuides
  /** US stocks flagged Low model rank in the latest run, each with how many stocks it ranked. */
  lowRanks?: Map<string, number>
}) {
  const rows = acted(holdings)
  const byKey = new Map(rows.map((h) => [positionKey(h.action), h]))
  const { cards, hold } = actionGroups(rows.map((h) => h.action))
  return (
    <div className="card card-pad enter" aria-labelledby="actions-h">
      <div className="section-head">
        <h2 id="actions-h">Actions</h2>
        <span className="sub">
          Sell → Trim → Review → Add → Hold{asOf && rows.length > 0 && ` · as of ${shortDay(asOf)}`}
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="empty">
          <Sparkles />
          <strong>No actions yet</strong>
          <span style={{ maxWidth: 440 }}>Actions appear after the next run that forecasts your holdings.</span>
        </div>
      ) : (
        <>
          {cards.length > 0 && (
            <div className="action-grid stagger">
              {cards.map((a, i) => {
                const h = byKey.get(positionKey(a)) as Acted
                const group = actionGroup(a) ?? 'hold'
                const tone = h.gainCad < 0 ? 'loss' : 'gain'
                const guide = guides.get(h.key)
                // a Sell's order replaces its stop
                const plan = joinPlans(guide?.order ?? null, a.action === 'sell' ? null : (guide?.stop ?? null))
                return (
                  <Link
                    key={h.key}
                    className={`action-card ${group}${group === 'sell' || group === 'trim' ? ' attention' : ''}`}
                    href={tickerHref(a.symbol, a.assetType)}
                    style={{ '--i': i } as CSSProperties}
                  >
                    <div className="flex items-center justify-between">
                      <span>
                        <span className={`chip ${group}`}>{group === 'review' ? 'Review' : ACTION_LABELS[a.action]}</span>
                        {/* a Sell or Trim keeps its own group; its review flag shows beside it */}
                        {group !== 'review' && a.review && (
                          <>
                            {' '}
                            <span className="chip review">Review</span>
                          </>
                        )}
                      </span>
                      <span className="sub">
                        {ACCOUNT_LABELS[a.account]}
                        {group === 'review' && ` · ${ACTION_LABELS[a.action]}`}
                      </span>
                    </div>
                    <div>
                      <span className="sym">{a.symbol}</span> {h.name && <span className="sub">{h.name}</span>}
                      {a.assetType === 'stock' && lowRanks.has(a.symbol) && (
                        <>
                          {' '}
                          <LowRankChip scored={lowRanks.get(a.symbol) as number} />
                        </>
                      )}
                    </div>
                    <p style={{ fontSize: 13, margin: 0 }}>{cardReason(a)}</p>
                    <ExitPlanCardLines plan={a.exitPlan} currency={assetCurrency(a.assetType, a.symbol)} price={a.refPrice} />
                    <div className={`num ${tone}`} style={{ fontSize: 13 }}>
                      {fmtMoney(h.gainCad, { signed: true })} · {fmtPct(h.gainPct)}
                    </div>
                    <OrderGuide plan={plan} />
                  </Link>
                )
              })}
            </div>
          )}
          {hold.length > 0 && (
            <HoldList
              lines={hold.map((a) => {
                const h = byKey.get(positionKey(a)) as Acted
                return {
                  key: h.key,
                  symbol: a.symbol,
                  name: h.name,
                  text: holdText(a, assetCurrency(a.assetType, a.symbol)),
                  // the line shows the plan's range and sell-at, so it carries the plan's status (R17)
                  note: a.exitPlan === null ? null : statusNote(a.exitPlan),
                  lowRank: a.assetType === 'stock' ? (lowRanks.get(a.symbol) ?? null) : null,
                }
              })}
            />
          )}
        </>
      )}
    </div>
  )
}

/** The likely range, q10 to q90 around the median, on a ±12% scale with a zero line. */
function RangeBar({ q10, q50, q90 }: { q10: number; q50: number; q90: number }) {
  const SPAN = 12
  const pos = (v: number) => Math.max(0, Math.min(100, 50 + ((v * 100) / SPAN) * 50))
  const [left, mid, right] = [pos(q10), pos(q50), pos(q90)]
  const origin = right > left ? ((mid - left) / (right - left)) * 100 : 50
  const text = `Likely range q10 ${fmtPct(q10 * 100)}, median ${fmtPct(q50 * 100)}, q90 ${fmtPct(q90 * 100)}`
  return (
    <div className="range" role="img" aria-label={text} title={text}>
      <div className="track" />
      <div className="zero" style={{ left: '50%' }} />
      <div className="band" style={{ left: `${left}%`, width: `${right - left}%`, '--origin': `${origin}%` } as CSSProperties} />
      <div className="mid" style={{ left: `${mid}%` }} />
    </div>
  )
}

/** Trailing stops are in the asset's own currency: CAD on the TSX, USD for US stocks and coins. */
const stopCurrency = (h: HoldingRow): 'CAD' | 'USD' => (h.market === 'TSX' ? 'CAD' : 'USD')

const dash = <span className="sub">—</span>

const hasRange = (a: HoldingAction) => a.q10 !== null && a.q50 !== null && a.q90 !== null
/** A row stored before exit plans existed shows its exit-by date instead. */
const exitByOf = (a: HoldingAction) => (a.exitPlan === null ? a.exitBy : null)
const hasFacts = (a: HoldingAction) => hasRange(a) || a.trailingStop !== null || a.riskLevel !== null || exitByOf(a) !== null

/**
 * The model's facts under a holding's name: the likely range, the trailing stop, the risk level and the exit-by
 * date of a row without a plan. Each only when the run gave it.
 */
function ModelFacts({ h, a }: { h: HoldingRow; a: HoldingAction }) {
  if (!hasFacts(a)) return null
  const range = hasRange(a)
  const exitBy = exitByOf(a)
  return (
    <div className="h-facts">
      {range && (
        <span className="h-range">
          <RangeBar q10={a.q10 as number} q50={a.q50 as number} q90={a.q90 as number} />
          {a.horizonDays !== null && <span className="num">{a.horizonDays}d</span>}
        </span>
      )}
      {a.trailingStop !== null && (
        <span className="h-stop">
          Trailing stop <span className="num">{fmtPrice(a.trailingStop, stopCurrency(h))}</span>
        </span>
      )}
      {a.riskLevel !== null && (
        <span className="h-risk">
          <span className={`dot ${a.riskLevel.replace('_', '-')}`} />
          {RISK_LABELS[a.riskLevel]} risk
        </span>
      )}
      {exitBy !== null && (
        <span className="h-exit-by">
          Exit by <span className="num">{shortDay(exitBy)}</span>
        </span>
      )}
    </div>
  )
}

/** The exit plan's compact lines and, with a sell-at price for the action, a link that opens the price-alert form prefilled. */
function ExitPlanLines({ a }: { a: HoldingAction }) {
  if (a.exitPlan === null) return null
  return (
    <div className="h-exit">
      <ExitPlanWithAlert
        plan={a.exitPlan}
        action={a.action}
        symbol={a.symbol}
        assetType={a.assetType}
        currency={assetCurrency(a.assetType, a.symbol)}
        price={a.refPrice}
        benchmark={planBenchmark(a.assetType, a.symbol)}
        compact
      />
    </div>
  )
}

export function WarningsCard({ warnings }: { warnings: Warning[] }) {
  return (
    <div className="card card-pad enter" aria-labelledby="warn-h">
      <div className="section-head" style={{ marginBottom: 2 }}>
        <h2 id="warn-h">Warnings</h2>
        <span className="sub">not tax advice</span>
      </div>
      {warnings.length === 0 ? (
        <p className="sub" style={{ margin: '8px 0 0' }}>
          None. TFSA trading frequency, superficial losses and sector weights are checked here.
        </p>
      ) : (
        warnings.map((w) => (
          <div className="warning" key={`${w.title}:${w.detail}`}>
            <TriangleAlert />
            <strong>{w.title}</strong>
            <p>{w.detail}</p>
          </div>
        ))
      )}
    </div>
  )
}

const MARKET_COLOURS: Record<string, string> = { US: 'var(--chart-1)', TSX: 'var(--chart-2)', Crypto: 'var(--chart-3)' }
const RISK_COLOURS: Record<string, string> = {
  [RISK_LABELS.low]: 'var(--risk-low)',
  [RISK_LABELS.medium]: 'var(--risk-medium)',
  [RISK_LABELS.high]: 'var(--risk-high)',
  [RISK_LABELS.very_high]: 'var(--risk-very-high)',
  [NOT_RATED]: 'var(--hold)',
}
const ACCOUNT_COLOURS: Record<string, string> = {
  [ACCOUNT_LABELS.tfsa]: 'var(--chart-1)',
  [ACCOUNT_LABELS.rrsp]: 'var(--chart-2)',
  [ACCOUNT_LABELS.fhsa]: 'var(--chart-4)',
  [ACCOUNT_LABELS.non_registered]: 'var(--hold)',
  [ACCOUNT_LABELS.crypto]: 'var(--chart-3)',
}

function Stack({ title, slices, colours }: { title: string; slices: Slice[]; colours: Record<string, string> }) {
  return (
    <div>
      <span className="label">{title}</span>
      <div className="stack" style={{ marginTop: 8 }} role="img" aria-label={slices.map((s) => `${s.label} ${s.share.toFixed(1)}%`).join(', ')}>
        {slices.map((s) => (
          <span key={s.label} style={{ width: `${s.share}%`, background: colours[s.label] }} />
        ))}
      </div>
      <div className="stack-legend">
        {slices.map((s) => (
          <span key={s.label}>
            {s.label} <b>{s.share.toFixed(1)}%</b>
          </span>
        ))}
      </div>
    </div>
  )
}

/** By risk level, market and account (spec §7.4). By risk shows once a run has rated a holding. */
export function BreakdownCard({ byRisk, byMarket, byAccount }: { byRisk: Slice[]; byMarket: Slice[]; byAccount: Slice[] }) {
  return (
    <div className="card card-pad enter" aria-labelledby="mix-h">
      <h2 id="mix-h" style={{ marginBottom: 12 }}>
        Breakdown
      </h2>
      {byMarket.length === 0 ? (
        <p className="sub" style={{ margin: 0 }}>
          Appears with your first holding.
        </p>
      ) : (
        <div className="grid gap-4">
          {byRisk.some((s) => s.label !== NOT_RATED) && <Stack title="By risk" slices={byRisk} colours={RISK_COLOURS} />}
          <Stack title="By market" slices={byMarket} colours={MARKET_COLOURS} />
          <Stack title="By account" slices={byAccount} colours={ACCOUNT_COLOURS} />
        </div>
      )}
    </div>
  )
}

/** A holding's return today: CAD and percent, then "on Fri" when the last close is from an earlier day. */
function DayCell({ r, today }: { r: HoldingRow['today']; today: string }) {
  if (r === null) return <td className="r num h-day">{dash}</td>
  const tone = r.cad < 0 ? 'loss' : 'gain'
  const when = moveWhen(r.day, today)
  return (
    <td className={`r num h-day ${tone}`}>
      <span>{fmtMoney(r.cad, { signed: true })}</span> {r.pct !== null && <span className={`sub ${tone}`}>{fmtPct(r.pct)}</span>}
      {when !== 'today' && <span className="sub h-when">{when}</span>}
    </td>
  )
}

/** Weight bars are drawn on a scale that 20% of the portfolio fills, or the largest holding when it is bigger. */
const WEIGHT_SCALE = 20

/**
 * Every holding (spec §7.2): account, action chip, shares, value in CAD, today's return, the all-time P/L and weight,
 * with the model's facts,
 * the exit plan, the stop order to keep and the notes under its name. A table on a wide screen, compact rows on a
 * phone (pages.css, same markup). The weight bar is orange on a Trim: the run says the holding is too big.
 */
export function HoldingsCard({
  holdings,
  accounts,
  guides,
  qtys,
  asOf,
  today,
}: {
  holdings: HoldingRow[]
  accounts: number
  guides: HoldingGuides
  /** Each open position's quantity, by position key. */
  qtys: Map<string, number>
  /** The day of the run the actions come from. */
  asOf: string | null
  /** Toronto's today: a day return from an older close (a weekend) names its day. */
  today: string
}) {
  const modelled = holdings.some((h) => h.action !== null)
  const total = holdings.reduce((sum, h) => sum + h.valueCad, 0)
  const weightOf = (h: HoldingRow) => (total > 0 ? (h.valueCad / total) * 100 : 0)
  const scale = Math.max(WEIGHT_SCALE, ...holdings.map(weightOf))
  return (
    <section className="card card-pad enter" aria-labelledby="hold-h">
      <div className="section-head">
        <h2 id="hold-h">
          Holdings <span className="count">{holdings.length}</span>
        </h2>
        <span className="sub">
          {accounts} {accounts === 1 ? 'account' : 'accounts'}
          {modelled && asOf && ` · actions as of ${shortDay(asOf)}`}
        </span>
      </div>
      {!modelled && (
        <div className="before-note">
          <Info />
          <span>Actions, likely ranges, trailing stops, exit plans and risk levels appear once the model runs.</span>
        </div>
      )}
      {holdings.length === 0 ? (
        <p className="sub" style={{ margin: 0 }}>
          No holdings yet.
        </p>
      ) : (
        <div className="table-scroll holdings-scroll">
          <table className="data-table" id="holdings">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Account</th>
                {modelled && <th>Action</th>}
                <th className="r h-shares">Shares</th>
                <th className="r">Value</th>
                <th className="r">Today</th>
                <th className="r">All-time</th>
                <th className="r">Weight</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const a = h.action
                const tone = h.gainCad < 0 ? 'loss' : 'gain'
                const stop = guides.get(h.key)?.stop?.steps.map((s) => s.text).join(' · ') || null
                const qty = qtys.get(h.key)
                const weight = weightOf(h)
                const about = [h.name, h.market].filter(Boolean).join(' · ')
                const noted = stop !== null || h.notes.length > 0
                const detailed = noted || (a !== null && (a.exitPlan !== null || hasFacts(a)))
                return (
                  <tr key={h.key}>
                    <td className="h-sym">
                      <div className="h-name">
                        <Link className="sym" href={tickerHref(h.symbol, h.market === null ? 'crypto' : 'stock')}>
                          {h.symbol}
                        </Link>
                        {about && <span className="sub">{about}</span>}
                      </div>
                      {detailed && (
                        <div className="h-detail">
                          {a && <ModelFacts h={h} a={a} />}
                          {a && <ExitPlanLines a={a} />}
                          {noted && (
                            <div className="h-note">
                              {stop && <span className="sub order-note">{stop}</span>}
                              {h.notes.map((n) =>
                                n.warn ? (
                                  <span key={n.text} className="warn-cell">
                                    <TriangleAlert />
                                    {n.text}
                                  </span>
                                ) : (
                                  <span key={n.text} className="sub">
                                    {n.text}
                                  </span>
                                ),
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="sub h-acct">{ACCOUNT_LABELS[h.account]}</td>
                    {modelled && (
                      <td className="h-action">
                        {a === null ? (
                          dash
                        ) : (
                          <span className="h-chips">
                            <span className={`chip ${a.action}`}>{ACTION_LABELS[a.action]}</span>
                            {a.review && <span className="chip review">Review</span>}
                          </span>
                        )}
                      </td>
                    )}
                    <td className="r num h-shares">{qty === undefined ? dash : fmtQty(qty)}</td>
                    <td className="r num h-value" data-price={h.priceMove ?? undefined}>
                      {fmtMoney(h.valueCad)}
                    </td>
                    <DayCell r={h.today} today={today} />
                    <td className={`r num h-pl ${tone}`}>
                      <span>{fmtMoney(h.gainCad, { signed: true })}</span> <span className={`sub ${tone}`}>{fmtPct(h.gainPct)}</span>
                    </td>
                    <td className="r num h-weight">
                      {weight.toFixed(1)}%
                      <span className={a?.action === 'trim' ? 'weight trim' : 'weight'} aria-hidden="true">
                        <i style={{ width: `${(weight / scale) * 100}%` }} />
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <PlanFootnote plans={holdings.map((h) => (h.action === null ? null : { plan: h.action.exitPlan, action: h.action.action }))} />
    </section>
  )
}
