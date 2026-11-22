import { ChevronRight } from 'lucide-react'
import Link from 'next/link'
import { ExitPlanWithAlert } from '@/components/portfolio/ExitPlan'
import type { HeldPlan } from '@/lib/data/ticker'
import { fmtMoney, fmtPct, fmtQty } from '@/lib/format'
import { ACTION_LABELS } from '@/lib/portfolio/actions'
import { assetCurrency } from '@/lib/portfolio/exit-plan'
import { ACCOUNT_LABELS, type AssetType, type Currency, type Position } from '@/lib/portfolio/types'
import { positionFigures } from '@/lib/ticker'

/**
 * Your position (spec §7.7, ticker_2.html), only when held: per account, the shares, value, average cost and
 * P/L in CAD, the run's action, and the exit plan's lines as `ExitPlanWithAlert` shows them, with its rules for
 * when a sell-at price is shown, in the asset's own currency. `price` is the last price in `currency`.
 */
export function PositionCard({
  symbol,
  assetType,
  positions,
  held,
  price,
  currency,
  usdCad,
  benchmark,
}: {
  symbol: string
  assetType: AssetType
  positions: Position[]
  /** The newest published run's action rows for this asset, one per account. */
  held: HeldPlan[]
  price: number | null
  currency: Currency
  usdCad: number | null
  benchmark: string
}) {
  const planCurrency = assetCurrency(assetType, symbol)
  const planned = held.some((h) => h.exitPlan !== null)
  return (
    <section className="card card-pad enter t-position" aria-labelledby="position-h" id="position">
      <div className="section-head">
        <h2 id="position-h">Your position</h2>
        <span className="label">values in CAD</span>
      </div>
      {positions.map((p) => {
        const h = held.find((x) => x.account === p.account)
        const f = positionFigures(p.qty, p.costCad, price, currency, usdCad)
        return (
          <div key={p.account} className="own" data-testid="position">
            <div className="own-top">
              <span className="own-title">
                <b>You own {fmtQty(p.qty)}</b>
                <span className="label">{ACCOUNT_LABELS[p.account]}</span>
              </span>
              {h?.action && <span className={`chip ${h.action}`}>{ACTION_LABELS[h.action]}</span>}
            </div>
            <div className="stats own-stats">
              <div className="stat">
                <span className="label">Value</span>
                <b className="num">{f.valueCad === null ? '—' : fmtMoney(f.valueCad)}</b>
              </div>
              <div className="stat">
                <span className="label">Avg cost</span>
                <b className="num">{f.avgCostCad === null ? '—' : fmtMoney(f.avgCostCad, { digits: 2 })}</b>
              </div>
              <div className="stat">
                <span className="label">P/L</span>
                <b className={`num ${f.gainCad === null ? '' : f.gainCad < 0 ? 'loss' : 'gain'}`}>
                  {f.gainCad === null ? '—' : fmtMoney(f.gainCad, { signed: true })}
                </b>
                {f.gainPct !== null && <span className="num sub">{fmtPct(f.gainPct)}</span>}
              </div>
            </div>
            {h?.exitPlan && (
              <div className="exit-plan">
                <span className="label">Exit plan · {planCurrency}</span>
                <ExitPlanWithAlert
                  plan={h.exitPlan}
                  action={h.action}
                  symbol={symbol}
                  assetType={assetType}
                  currency={planCurrency}
                  price={h.refPrice}
                  benchmark={benchmark}
                />
              </div>
            )}
          </div>
        )
      })}
      {planned && (
        <Link className="link own-link" href="/portfolio">
          Full exit plan and orders <ChevronRight aria-hidden="true" />
        </Link>
      )}
    </section>
  )
}
