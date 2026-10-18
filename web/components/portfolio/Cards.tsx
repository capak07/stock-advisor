import { Info, Sparkles, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import { fmtAmount, fmtPct } from '@/lib/format'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'
import type { Slice } from '@/lib/portfolio/valuation'
import type { HoldingRow } from '@/lib/portfolio/view'
import type { Warning } from '@/lib/portfolio/warnings'
import { tickerHref } from '@/lib/ticker'

/** Sell, Trim, Review, Add and Hold come from the model (Plan 4); until then, this says so. */
export function ActionsCard() {
  return (
    <div className="card card-pad enter" aria-labelledby="actions-h">
      <div className="section-head">
        <h2 id="actions-h">Actions</h2>
        <span className="sub">Sell → Trim → Review → Add → Hold</span>
      </div>
      <div className="empty">
        <Sparkles />
        <strong>No actions yet</strong>
        <span style={{ maxWidth: 440 }}>
          Sell, Trim, Review, Add and Hold come from the model, which isn&apos;t trained yet. Until then, this page shows
          values and P/L, and the warnings that don&apos;t need the model.
        </span>
      </div>
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
          None. TFSA trading frequency and superficial losses are checked here.
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

/** By market and by account (spec §7.4). By risk level comes with the model. */
export function BreakdownCard({ byMarket, byAccount }: { byMarket: Slice[]; byAccount: Slice[] }) {
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
          <Stack title="By market" slices={byMarket} colours={MARKET_COLOURS} />
          <Stack title="By account" slices={byAccount} colours={ACCOUNT_COLOURS} />
        </div>
      )}
    </div>
  )
}

export function HoldingsCard({ holdings, accounts }: { holdings: HoldingRow[]; accounts: number }) {
  return (
    <section className="card card-pad enter" aria-labelledby="hold-h">
      <div className="section-head">
        <h2 id="hold-h">Holdings</h2>
        <span className="sub">
          {holdings.length} {holdings.length === 1 ? 'position' : 'positions'} · {accounts}{' '}
          {accounts === 1 ? 'account' : 'accounts'}
        </span>
      </div>
      <div className="before-note">
        <Info />
        <span>Actions, likely ranges, trailing stops, exit dates and risk levels appear once the model runs.</span>
      </div>
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
