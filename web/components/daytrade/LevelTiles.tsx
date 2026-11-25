import { MovePct } from '@/components/daytrade/MovePct'
import { barePrice, curOf, type DaytradeMarket } from '@/lib/daytrade'

/**
 * The entry, target and stop as three tiles, the target and the stop with how far each is from the entry.
 * The tiles are narrow three across, so the currency sits in the label ("Entry US$" over "68.12"). `entryNote`
 * goes under the entry ("10:40 AM", "Nov 25 open"); without one the line is held empty so the three line up.
 */
export function LevelTiles({
  entry,
  target,
  stop,
  market,
  entryLabel = 'Entry',
  entryNote,
}: {
  entry: number
  target: number
  stop: number
  market: DaytradeMarket
  entryLabel?: string
  entryNote?: string
}) {
  const cur = curOf(market)
  return (
    <div className="dt-levels">
      <div className="stat">
        <span className="label">
          {entryLabel} {cur}
        </span>
        <b>{barePrice(entry, market)}</b>
        {entryNote === undefined ? <MovePct from={entry} /> : <span className="lvl-pct lvl-note">{entryNote}</span>}
      </div>
      <div className="stat">
        <span className="label">Target {cur}</span>
        <b className="gain">{barePrice(target, market)}</b>
        <MovePct from={entry} to={target} tone="gain" />
      </div>
      <div className="stat">
        <span className="label">Stop {cur}</span>
        <b className="loss">{barePrice(stop, market)}</b>
        <MovePct from={entry} to={stop} tone="loss" />
      </div>
    </div>
  )
}
