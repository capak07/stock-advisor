import { CircleHelp, Eye, FlaskConical, Scale, ShieldAlert, Sparkles } from 'lucide-react'
import Link from 'next/link'
import type { CSSProperties } from 'react'
import { NoPicksSentence, PICK_BAR } from '@/components/picks/BestChance'
import { PickCard } from '@/components/picks/PickCard'
import type { MarketPicks as Picks, PickView, Style } from '@/lib/data/picks'
import type { Guide } from '@/lib/guidance'
import { pickCount } from '@/lib/picks'
import type { Run } from '@/lib/runs'
import { bestChanceLine, PICK_P_FLOOR, type BestChance } from '@/lib/today'

/** Spec §6.6's paper period: a style's picks are a trial until enough of them are graded live. */
const VALIDATED_AT: Record<Style, number> = { swing: 100, position: 50 }

/** The backtest a market's model needs before it may pick at all (the pipeline's gate: "needs 30"). */
const BACKTEST_PICKS = 30

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

/** Why one market shows no picks: no model, a failed gate, or nothing cleared the bar. */
function NoPicks({ market }: { market: Picks }) {
  const m = market.market
  const [icon, title, body] = !market.enabled
    ? market.reason === null
      ? [<Sparkles key="i" />, `No ${m} picks yet`, `${m} has no trained model yet.`]
      : [
          <ShieldAlert key="i" style={{ color: 'var(--loss)' }} />,
          `No ${m} picks today: model check failed`,
          `Why: ${market.reason}. Watchlist verdicts and holding actions still run.`,
        ]
    : [
        <Sparkles key="i" />,
        `No ${m} picks today`,
        `Nothing cleared the bar this run: P(beat) at least ${PICK_BAR} and an expected return above costs.`,
      ]
  return (
    <div className="card">
      <div className="empty">
        <div className="halo">{icon}</div>
        <strong>{title}</strong>
        <span style={{ maxWidth: 480 }}>{body}</span>
      </div>
    </div>
  )
}

/** One market's tab on Today's Picks: its Swing and Position lists, or why there are none. The early exits sit above the tabs (the page). */
export function MarketPicks({
  market,
  portfolioCad,
  usdFxFeePct,
  guideFor,
  actionFor,
}: {
  market: Picks
  portfolioCad: number | null
  usdFxFeePct: number
  guideFor?: (pick: PickView) => Guide | null
  actionFor?: (pick: PickView) => React.ReactNode
}) {
  return (
    <div className="grid gap-5">
      {pickCount(market) > 0 ? (
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
                    <PickCard
                      pick={p}
                      portfolioCad={portfolioCad}
                      usdFxFeePct={usdFxFeePct}
                      guide={guideFor?.(p)}
                      action={actionFor?.(p)}
                    />
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
  )
}

/** A market's own reason, one line under the explanation of an empty run. */
const marketNote = (m: Picks): string =>
  !m.enabled
    ? m.reason === null
      ? 'No trained model yet.'
      : `Model check failed: ${m.reason}.`
    : 'Nothing cleared the bar this run.'

const pctText = (p: number) => `${(p * 100).toFixed(1)}%`

/** The verdict on the run's best chance: a weak one reads as no clear edge, in words. */
function edgeLine(best: BestChance | null): React.ReactNode {
  if (best === null) return <b>There is no clear edge today.</b>
  const pct = pctText(best.pBeat)
  if (best.pBeat >= PICK_P_FLOOR) {
    return (
      <>
        <b>{pct} clears the {PICK_BAR} bar,</b> but nothing passed the rest of the rule: an expected return above costs, in a
        market whose model passed its backtest.
      </>
    )
  }
  return (
    <>
      <b>{pct} is {best.pBeat < 0.55 ? 'close to a coin flip' : `under the ${PICK_BAR} bar`}.</b> There is no clear edge today.
    </>
  )
}

/**
 * Today's Picks with nothing to show (spec §7.4, mockup picks_2.html's first half). Before any run:
 * "No run yet" (Review Focus 2). A run that picked nothing in either market: "No picks today", the
 * run's best chance against the 58% bar, links to the watchlist's verdicts and to the explanation,
 * then the explanation itself with each market's own reason. The best chance is the run's, never a
 * pick's.
 */
export function PicksEmpty({ run, chances, markets }: { run: Run | null; chances: BestChance[]; markets: Picks[] }) {
  if (run === null) {
    return (
      <section className="card enter" aria-labelledby="picks-none-h">
        <div className="empty picks-empty">
          <div className="halo">
            <Sparkles />
          </div>
          <h2 id="picks-none-h">No run yet</h2>
          <p className="muted">
            Picks appear after the first published run. Until then nothing here is a suggestion to buy. Your holdings are on
            My Portfolio.
          </p>
          <div className="picks-actions">
            <Link className="btn btn-secondary" href="/portfolio">
              Go to My Portfolio
            </Link>
          </div>
        </div>
      </section>
    )
  }
  const best = chances.reduce<BestChance | null>((top, c) => (top === null || c.pBeat > top.pBeat ? c : top), null)
  return (
    <section className="card enter" aria-labelledby="picks-none-h">
      <div className="empty picks-empty">
        <div className="halo">
          <Sparkles />
        </div>
        <h2 id="picks-none-h">No picks today</h2>
        <p className="muted">
          <NoPicksSentence bestChance={bestChanceLine(chances)} />
        </p>
        <div className="picks-actions">
          <Link className="btn btn-primary" href="/watchlist">
            <Eye aria-hidden />
            See the watchlist&apos;s verdicts
          </Link>
          <a className="btn btn-secondary" href="#picks-why">
            <CircleHelp aria-hidden />
            Why?
          </a>
        </div>
      </div>
      <div className="picks-why" id="picks-why">
        <div className="picks-why-tiles">
          <div className="stat">
            <span className="label">Best chance today</span>
            <b>{best === null ? '—' : pctText(best.pBeat)}</b>
            {best !== null && <span className="sub">vs {best.benchmark}</span>}
          </div>
          <div className="stat">
            <span className="label">A pick needs</span>
            <b>{PICK_BAR}</b>
          </div>
          <div className="stat">
            <span className="label">And a backtest of</span>
            <b>{BACKTEST_PICKS} picks</b>
          </div>
        </div>
        <div className="picks-why-text">
          <p className="picks-edge">
            <Scale aria-hidden />
            <span>{edgeLine(best)}</span>
          </p>
          <p>
            The model ranks stocks well: the ones it likes tend to do better than the ones it does not. But its honest chance of
            beating the market rarely strays far from a coin flip, because most stocks follow the market far more than any model
            can predict.
          </p>
          <p>
            Today nothing clears the bar: a pick needs a chance of at least {PICK_BAR}, an expected return above costs, and at
            least {BACKTEST_PICKS} backtest picks showing the rule worked after costs. So nothing here is a suggestion to buy. Your
            holdings and the watchlist verdicts still update on every run.
          </p>
          {markets.length > 0 && (
            <ul className="picks-markets">
              {markets.map((m) => (
                <li key={m.market} data-market={m.market.toLowerCase()}>
                  <span className="label">{m.market}</span>
                  <span>{marketNote(m)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}
