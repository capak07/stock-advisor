import { ChevronRight, TriangleAlert } from 'lucide-react'
import Link from 'next/link'
import { fmtPct } from '@/lib/format'
import { ACTION_LABELS, actionGroup, cardReason } from '@/lib/portfolio/actions'
import type { HoldingRow } from '@/lib/portfolio/view'
import type { Warning } from '@/lib/portfolio/warnings'
import { tickerHref } from '@/lib/ticker'

/**
 * Needs your attention (spec §7.1): the holdings whose latest action is Sell, Trim, Review or Add,
 * each with its chip, symbol, one-line reason and P/L; how many more are on Hold; then the
 * portfolio's warnings. One line when nothing needs action.
 */
export function AttentionCard({
  items,
  onHold,
  warnings,
  asOf,
}: {
  items: HoldingRow[]
  onHold: number
  warnings: Warning[]
  /** When the run behind the actions finished, e.g. "Nov 20 · pre-close 15:31"; null before the first. */
  asOf: string | null
}) {
  return (
    <section className="card card-pad enter" aria-labelledby="att-h">
      <div className="section-head">
        <h2 id="att-h">
          Needs your attention {items.length > 0 && <span className="count">{items.length}</span>}
        </h2>
        {asOf && <span className="label">{asOf}</span>}
      </div>
      {items.length === 0 && (
        <p className="sub" style={{ margin: '0 0 4px', fontSize: 13 }}>
          Nothing needs your attention.
        </p>
      )}
      {items.map((h) => {
        const a = h.action!
        const group = actionGroup(a) ?? 'hold'
        return (
          <Link key={h.key} className="row" href={tickerHref(a.symbol, a.assetType)} data-testid="attention-row">
            <span className={`chip ${group}`}>{group === 'review' ? 'Review' : ACTION_LABELS[a.action]}</span>
            <div style={{ minWidth: 0 }}>
              <div className="sym">{a.symbol}</div>
              <div className="name">{cardReason(a)}</div>
            </div>
            <span className={`num right ${h.gainPct < 0 ? 'loss' : 'gain'}`}>{fmtPct(h.gainPct)}</span>
          </Link>
        )
      })}
      {onHold > 0 && (
        <Link className="row" href="/portfolio">
          <span className="chip hold">Hold</span>
          <div className="name" style={{ fontSize: 13 }}>
            {onHold} {items.length > 0 ? 'more ' : ''}on Hold
          </div>
          <ChevronRight className="muted" style={{ width: 16, height: 16 }} aria-hidden />
        </Link>
      )}
      {warnings.map((w) => (
        <div className="today-warn" key={`${w.title}:${w.detail}`}>
          <TriangleAlert aria-hidden />
          <div>
            <strong>{w.title}</strong>
            <p>{w.detail}</p>
          </div>
        </div>
      ))}
    </section>
  )
}
