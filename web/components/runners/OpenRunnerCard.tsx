import Link from 'next/link'
import { More } from '@/components/More'
import { LevelTiles } from '@/components/daytrade/LevelTiles'
import { shortDay } from '@/lib/dates'
import { fmtR, priceOf, rTone } from '@/lib/daytrade'
import { fmtPct } from '@/lib/format'
import { PAPER_SHARES, paperValue, rSoFar, usdMoney, usdSigned, type PaperValue, type Runner } from '@/lib/runners'
import { LIVE_NOTE, liveValue, type LiveRunner } from '@/lib/runners-live'
import { tickerHref } from '@/lib/ticker'

const DASH = '—'
const usd = (value: number) => priceOf(value, 'US')

/**
 * An open runner as a paper position, leading with its answer (owner request 2026-11-25): the 100 shares' gain and
 * R, what they cost and are worth, then the bought / target / stop tiles and where the price stands. With `live`
 * (Yahoo's bars past the stored close) the answer is at the latest price or close, or the stop or target hit since;
 * otherwise at the stored close. The written-out lines go under Details. Display only: nothing here places an order.
 */
export function OpenRunnerCard({ runner: r, live = null }: { runner: Runner; live?: LiveRunner | null }) {
  const latest = live === null ? null : liveValue(live)
  const stored = r.lastClose !== null && r.lastDay !== null ? paperValue(r.entry, r.lastClose) : null
  const paper: PaperValue | null = latest?.paper ?? stored
  const rNow = latest === null ? rSoFar(r) : latest.r
  const exited = live?.kind === 'exited'
  const where =
    latest !== null
      ? latest.lead
      : r.lastClose !== null && r.lastDay !== null
        ? `${shortDay(r.lastDay)} close ${usd(r.lastClose)}`
        : 'No close yet'
  return (
    <article className="card pick dt-card" data-testid="open-runner-card" aria-label={`${r.symbol} open runner`}>
      <div className="dt-who-t">
        <span>
          <Link className="sym" href={tickerHref(r.symbol, 'stock')}>
            {r.symbol}
          </Link>
        </span>
        {r.name && <span className="name">{r.name}</span>}
      </div>
      <div className="answer">
        {paper === null ? (
          <b className="answer-big">No close yet</b>
        ) : (
          <>
            <span className="answer-row">
              <b className={`answer-big num ${rTone(paper.gain) ?? ''}`.trim()} data-testid="open-runner-gain">
                {`${usdSigned(paper.gain)} ${fmtPct(paper.gainPct)}`}
              </b>
              <b className={`answer-r num ${rTone(rNow) ?? ''}`.trim()} data-testid="open-runner-r">
                {rNow === null ? DASH : fmtR(rNow)}
              </b>
            </span>
            <span className="answer-note">
              {`${PAPER_SHARES} shares: paid ${usdMoney(paper.cost)} · ${exited ? 'got back' : 'worth'} ${usdMoney(paper.value)}`}
            </span>
          </>
        )}
      </div>
      {r.entry !== null && (
        <LevelTiles
          entry={r.entry}
          target={r.target}
          stop={r.stop}
          market="US"
          entryLabel="Bought"
          entryNote={r.entryDay === null ? undefined : shortDay(r.entryDay)}
        />
      )}
      <p className="dt-line sub">{exited ? where : `${where} · hold until ${shortDay(r.holdBy)}`}</p>
      <More testId="open-runner-details">
        <ul className="dt-lines">
          {r.entry !== null && (
            <li>{`Bought ${PAPER_SHARES} shares at ${usd(r.entry)}${r.entryDay === null ? '' : ` on ${shortDay(r.entryDay)}`} = ${usdMoney(r.entry * PAPER_SHARES)}`}</li>
          )}
          {latest !== null && <li>{latest.text}</li>}
          {r.lastClose !== null && r.lastDay !== null && stored !== null && (
            <li>{`${shortDay(r.lastDay)} close ${usd(r.lastClose)} (the last morning check): worth ${usdMoney(stored.value)}`}</li>
          )}
          <li>{`${exited ? 'R at the exit' : 'R so far'} ${rNow === null ? DASH : fmtR(rNow)}`}</li>
        </ul>
        {latest !== null && <p className="dt-live-note">{LIVE_NOTE}</p>}
      </More>
    </article>
  )
}
