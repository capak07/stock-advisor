import { Info, Sparkles, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import type { CSSProperties } from 'react'
import { shortDay } from '@/lib/dates'
import { fmtAmount, fmtMoney, fmtPct, fmtPrice } from '@/lib/format'
import {
  ACTION_LABELS,
  RISK_LABELS,
  actionGroup,
  actionGroups,
  cardReason,
  holdText,
  type HoldingAction,
} from '@/lib/portfolio/actions'
import { positionKey } from '@/lib/portfolio/ledger'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import { NOT_RATED, type Slice } from '@/lib/portfolio/valuation'
import type { HoldingRow } from '@/lib/portfolio/view'
import type { Warning } from '@/lib/portfolio/warnings'
import { tickerHref } from '@/lib/ticker'
import { HoldList } from './HoldList'

/** A holding with its latest run action. */
type Acted = HoldingRow & { action: HoldingAction }

const acted = (holdings: readonly HoldingRow[]): Acted[] => holdings.filter((h): h is Acted => h.action !== null)

/** Sell → Trim → Review → Add cards from the latest run's actions, then the plain Holds folded (spec §7.2, §7.3). */
export function ActionsCard({ holdings, asOf }: { holdings: HoldingRow[]; asOf: string | null }) {
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
                    </div>
                    <p style={{ fontSize: 13, margin: 0 }}>{cardReason(a)}</p>
                    <div className={`num ${tone}`} style={{ fontSize: 13 }}>
                      {fmtMoney(h.gainCad, { signed: true })} · {fmtPct(h.gainPct)}
                    </div>
                  </Link>
                )
              })}
            </div>
          )}
          {hold.length > 0 && (
            <HoldList
              lines={hold.map((a) => {
                const h = byKey.get(positionKey(a)) as Acted
                return { key: h.key, symbol: a.symbol, name: h.name, text: holdText(a) }
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

/** Action, likely range, trailing stop, exit by and risk; dashes for a holding the run didn't cover. */
function ModelCells({ h }: { h: HoldingRow }) {
  const a = h.action
  if (a === null) {
    return (
      <>
        <td className="h-action">{dash}</td>
        <td className="h-range">{dash}</td>
        <td className="r h-stop">{dash}</td>
        <td className="h-exit">{dash}</td>
        <td className="h-risk">{dash}</td>
      </>
    )
  }
  return (
    <>
      <td className="h-action">
        <span className={`chip ${a.action}`}>{ACTION_LABELS[a.action]}</span>
        {a.review && (
          <>
            {' '}
            <span className="chip review">Review</span>
          </>
        )}
      </td>
      <td className="h-range">
        {a.q10 !== null && a.q50 !== null && a.q90 !== null ? (
          <div className="flex items-center gap-2">
            <RangeBar q10={a.q10} q50={a.q50} q90={a.q90} />
            {a.horizonDays !== null && <span className="sub num">{a.horizonDays}d</span>}
          </div>
        ) : (
          dash
        )}
      </td>
      <td className="r num h-stop">{a.trailingStop === null ? dash : fmtPrice(a.trailingStop, stopCurrency(h))}</td>
      <td className="num h-exit">{a.exitBy === null ? dash : shortDay(a.exitBy)}</td>
      <td className="h-risk">
        {a.riskLevel === null ? (
          dash
        ) : (
          <span className="badge">
            <span className={`dot ${a.riskLevel.replace('_', '-')}`} />
            {RISK_LABELS[a.riskLevel]}
          </span>
        )}
      </td>
    </>
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

export function HoldingsCard({ holdings, accounts }: { holdings: HoldingRow[]; accounts: number }) {
  const modelled = holdings.some((h) => h.action !== null)
  return (
    <section className="card card-pad enter" aria-labelledby="hold-h">
      <div className="section-head">
        <h2 id="hold-h">Holdings</h2>
        <span className="sub">
          {holdings.length} {holdings.length === 1 ? 'position' : 'positions'} · {accounts}{' '}
          {accounts === 1 ? 'account' : 'accounts'}
        </span>
      </div>
      {!modelled && (
        <div className="before-note">
          <Info />
          <span>Actions, likely ranges, trailing stops, exit dates and risk levels appear once the model runs.</span>
        </div>
      )}
      {holdings.length === 0 ? (
        <p className="sub" style={{ margin: 0 }}>
          No holdings yet.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table" id="holdings">
            <thead>
              <tr>
                <th>Account</th>
                <th>Symbol</th>
                <th>Market</th>
                <th className="r">Value C$</th>
                <th className="r">P/L C$</th>
                {modelled && (
                  <>
                    <th>Action</th>
                    <th>Likely range</th>
                    <th className="r">Trailing stop</th>
                    <th>Exit by</th>
                    <th>Risk</th>
                  </>
                )}
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const tone = h.gainCad < 0 ? 'loss' : 'gain'
                return (
                  <tr key={h.key}>
                    <td className="sub h-acct">{ACCOUNT_LABELS[h.account]}</td>
                    <td className="h-sym">
                      <Link className="sym" href={tickerHref(h.symbol, h.market === null ? 'crypto' : 'stock')}>
                        {h.symbol}
                      </Link>
                      {h.name && (
                        <>
                          <br />
                          <span className="sub">{h.name}</span>
                        </>
                      )}
                    </td>
                    <td className={h.market ? 'h-mkt' : 'sub h-mkt'}>{h.market ?? '—'}</td>
                    <td className="r num h-value">{fmtAmount(h.valueCad)}</td>
                    <td className={`r num h-pl ${tone}`}>
                      {fmtAmount(h.gainCad, { signed: true })}
                      <br />
                      <span className={`sub ${tone}`}>{fmtPct(h.gainPct)}</span>
                    </td>
                    {modelled && <ModelCells h={h} />}
                    <td className="h-note">
                      {h.notes.length === 0 ? (
                        <span className="sub">—</span>
                      ) : (
                        h.notes.map((n) =>
                          n.warn ? (
                            <span key={n.text} className="warn-cell">
                              <TriangleAlert />
                              {n.text}
                            </span>
                          ) : (
                            <span key={n.text} className="sub" style={{ display: 'block' }}>
                              {n.text}
                            </span>
                          ),
                        )
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
