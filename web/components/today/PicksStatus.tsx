import { ChevronRight, Sparkles } from 'lucide-react'
import Link from 'next/link'
import type { MarketPicks } from '@/lib/data/picks'
import type { Run } from '@/lib/runs'
import { PICK_P_FLOOR } from '@/lib/today'

const count = (m: MarketPicks) => m.swing.length + m.position.length
const BAR = `${Math.round(PICK_P_FLOOR * 100)}%`

/**
 * Today's Picks card (spec §7.1): the count per market when the latest run picked anything;
 * otherwise "None today" with the run's best chance of beating the market against the picks' bar.
 * The best chance is a fact about the run, never shown on a pick card. Before any run: "No run yet".
 */
export function PicksStatus({
  run,
  markets,
  bestChance,
}: {
  run: Run | null
  markets: MarketPicks[]
  /** `bestChanceLine` of the run, e.g. "US 52.7% vs SPY · TSX 55.1% vs XIU.TO"; null when it has none. */
  bestChance: string | null
}) {
  const total = markets.reduce((sum, m) => sum + count(m), 0)
  return (
    <section className="card card-pad enter" aria-labelledby="pk-h">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="pk-h">
          <Sparkles style={{ width: 18, height: 18, color: 'var(--brand)' }} aria-hidden />
          Picks
        </h2>
        {run === null ? (
          <span className="chip neutral">No run yet</span>
        ) : total === 0 ? (
          <span className="chip neutral">None today</span>
        ) : (
          <Link className="link" href="/picks">
            Open <ChevronRight style={{ width: 14, height: 14 }} aria-hidden />
          </Link>
        )}
      </div>
      {run === null ? (
        <p className="sub" style={{ margin: '6px 0 0', fontSize: 13.5 }}>
          No run yet. Picks appear after the first published run.
        </p>
      ) : total === 0 ? (
        <>
          <p className="muted" style={{ margin: '6px 0 12px', fontSize: 13.5 }}>
            {bestChance !== null && (
              <>
                The best chance of beating the market was <span className="num">{bestChance}</span>; a pick needs {BAR}.{' '}
              </>
            )}
            Nothing has enough evidence to buy.
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Link className="btn btn-secondary btn-sm" href="/picks">
              Why none?
            </Link>
            <Link className="btn btn-ghost btn-sm" href="/watchlist">
              Watchlist verdicts
            </Link>
          </div>
        </>
      ) : (
        <div className="stats" style={{ marginTop: 8 }}>
          {markets.map((m) => {
            const n = count(m)
            return (
              <div className="stat" key={m.market}>
                <span className="label">{m.market}</span>
                <b>{n === 0 ? 'None' : `${n} ${n === 1 ? 'pick' : 'picks'}`}</b>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
