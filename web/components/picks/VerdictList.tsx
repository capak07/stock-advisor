import Link from 'next/link'
import type { ExitView, VerdictView } from '@/lib/data/picks'
import { fmtPct, fmtPrice } from '@/lib/format'
import type { Market } from '@/lib/portfolio/types'
import { tickerHref } from '@/lib/ticker'
import { VERDICT_LABEL, verdictWhy } from '@/lib/verdicts'

/** The run's verdict for every watched symbol: market, chip and a short why. */
export function VerdictList({ verdicts }: { verdicts: VerdictView[] }) {
  return (
    <div className="card card-pad">
      <div className="section-head" style={{ marginBottom: 2 }}>
        <h2>Watchlist verdicts</h2>
        <Link href="/watchlist" className="sub">
          Edit
        </Link>
      </div>
      {verdicts.length === 0 ? (
        <p className="sub" style={{ margin: '10px 0 0' }}>
          Nothing watched this run. Add symbols on the Watchlist to get a verdict each run.
        </p>
      ) : (
        <div className="verdicts">
          {verdicts.map((v) => (
            <div key={`${v.assetType}:${v.symbol}`} className="verdict">
              <Link className="sym" href={tickerHref(v.symbol, v.assetType)}>
                {v.symbol}
              </Link>
              <span className="sub" style={{ gridColumn: 'auto' }}>
                {v.market ?? 'Crypto'}
              </span>
              <span className={`chip ${v.verdict}`}>{VERDICT_LABEL[v.verdict]}</span>
              <span className="sub">{verdictWhy(v, 'short')}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const STYLE = { swing: 'Swing', position: 'Position' } as const

/** The picks this run told the owner to exit (Plan 4c); hidden when there are none. */
export function ExitEarlyCard({ market, exits }: { market: Market; exits: ExitView[] }) {
  if (exits.length === 0) return null
  return (
    <div className="card card-pad" id={`exit-early-${market.toLowerCase()}`}>
      <h2 style={{ marginBottom: 6 }}>Exit early</h2>
      {exits.map((e) => (
        <div key={e.id} className="verdict">
          <Link className="sym" href={tickerHref(e.symbol, 'stock')}>
            {e.symbol}
          </Link>
          <span className="sub" style={{ gridColumn: 'auto' }}>
            {STYLE[e.style]} · {e.horizon}d
          </span>
          <span className="chip sell">Exit</span>
          <span className="sub">
            {e.reason === 'stop' ? 'stop hit' : 'P fell to 0.42 or below'} · exited at{' '}
            {fmtPrice(e.exitPrice, market === 'US' ? 'USD' : 'CAD')} ·{' '}
            <span className={`num ${e.ret < 0 ? 'loss' : 'gain'}`}>{fmtPct(e.ret * 100)}</span>
          </span>
        </div>
      ))}
    </div>
  )
}
