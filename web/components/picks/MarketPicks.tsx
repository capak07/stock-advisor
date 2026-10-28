import { FlaskConical, ShieldAlert, Sparkles } from 'lucide-react'
import type { CSSProperties } from 'react'
import { PickCard } from '@/components/picks/PickCard'
import { ExitEarlyCard, VerdictList } from '@/components/picks/VerdictList'
import type { MarketPicks as Picks, PickView, Style, VerdictView } from '@/lib/data/picks'

/** Spec §6.6's paper period: a style's picks are a trial until enough of them are graded live. */
const VALIDATED_AT: Record<Style, number> = { swing: 100, position: 50 }

function PaperBanner({ style, graded }: { style: Style; graded: number }) {
  if (graded >= VALIDATED_AT[style]) return null
  return (
    <div className="banner warn paper-banner" style={{ marginBottom: 10 }}>
      <FlaskConical />
      {style === 'swing' ? (
        <div>
          <strong>Not yet validated.</strong> {graded} of 100 Swing picks graded live; treat these as a paper trial.
        </div>
      ) : (
        <div>
          <strong>Validated on backtest only.</strong> {graded} of 50 Position picks graded live.
        </div>
      )}
    </div>
  )
}

const LISTS: { style: Style; title: string; span: string }[] = [
  { style: 'swing', title: 'Swing', span: '2 days to 4 weeks' },
  { style: 'position', title: 'Position', span: '1 to 6 months' },
]

function Empty({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="empty">
        {icon}
        <strong>{title}</strong>
        <span style={{ maxWidth: 480 }}>{children}</span>
      </div>
    </div>
  )
}

/** Why a market shows no picks: no model, a failed gate, or nothing cleared the bar. */
function NoPicks({ market }: { market: Picks }) {
  const m = market.market
  if (!market.enabled && market.reason === null) {
    return (
      <Empty icon={<Sparkles />} title={`No ${m} picks yet`}>
        {m} has no trained model yet.
      </Empty>
    )
  }
  if (!market.enabled) {
    return (
      <Empty icon={<ShieldAlert style={{ color: 'var(--loss)' }} />} title={`No ${m} picks today: model check failed`}>
        Why: {market.reason}. Watchlist verdicts and holding actions still run.
      </Empty>
    )
  }
  return (
    <Empty icon={<Sparkles />} title={`No ${m} picks today`}>
      Nothing cleared the bar this run: P(beat) at least 58% and an expected return above costs.
    </Empty>
  )
}

/** One market's tab on Today's Picks: its Swing and Position lists, or why there are none, beside the verdicts. */
export function MarketPicks({
  market,
  verdicts,
  portfolioCad,
  usdFxFeePct,
  actionFor,
}: {
  market: Picks
  verdicts: VerdictView[]
  portfolioCad: number | null
  usdFxFeePct: number
  actionFor?: (pick: PickView) => React.ReactNode
}) {
  const shown = market.enabled && market.swing.length + market.position.length > 0
  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]" style={{ alignItems: 'start' }}>
      <div className="grid gap-5">
        {shown ? (
          LISTS.filter((l) => market[l.style].length > 0).map((l) => {
            const picks = market[l.style]
            return (
              <div key={l.style} className="pick-list" data-style={l.style}>
                <div className="list-head">
                  <h2>
                    {l.title} <span className="sub">{l.span}</span>
                  </h2>
                  <span className="sub num">
                    {picks.length} {picks.length === 1 ? 'pick' : 'picks'}
                  </span>
                </div>
                <PaperBanner style={l.style} graded={market.graded[l.style]} />
                <div className="pick-grid stagger">
                  {picks.map((p, i) => (
                    <div key={p.id} style={{ '--i': i, display: 'grid' } as CSSProperties}>
                      <PickCard pick={p} portfolioCad={portfolioCad} usdFxFeePct={usdFxFeePct} action={actionFor?.(p)} />
                    </div>
                  ))}
                </div>
              </div>
            )
          })
        ) : (
          <NoPicks market={market} />
        )}
      </div>
      <aside className="grid gap-4">
        <ExitEarlyCard market={market.market} exits={market.exitedEarly} />
        <VerdictList verdicts={verdicts} />
      </aside>
    </section>
  )
}
