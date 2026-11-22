import type { Close } from './types'

/** A position's return on its latest price day, in CAD and in percent. */
export interface DayReturn {
  cad: number
  /** In the asset's own currency for a move between two closes; null for a free position bought that day. */
  pct: number | null
  /** The day of the latest price (a live quote's Toronto day after a Refresh). */
  day: string
}

/**
 * Today's return, as a broker shows it: the latest price against the close before it, times the shares. A position
 * opened since that close counts from what it cost instead. Shares added to an older position on the latest day
 * count from the close before (the ledger keeps one average cost). Two closes in different currencies (a coin's CAD
 * quote on its USD history) compare in CAD at `usdCad`; a US stock's move converts to CAD at it. Null without a
 * latest price, without a close before for a position held before it, or without a rate it needs.
 */
export function dayReturn(
  position: { qty: number; costCad: number; openedOn: string },
  latest: Close | null,
  previous: Close | null,
  usdCad: number | null,
): DayReturn | null {
  if (latest === null) return null
  const cad = (c: Close) => (c.currency === 'CAD' ? c.close : usdCad === null ? null : c.close * usdCad)
  const opened = position.openedOn >= latest.day || (previous !== null && position.openedOn > previous.day)
  if (opened) {
    const priceCad = cad(latest)
    if (priceCad === null) return null
    const gain = position.qty * priceCad - position.costCad
    return { cad: gain, pct: position.costCad > 0 ? (gain / position.costCad) * 100 : null, day: latest.day }
  }
  if (previous === null) return null
  const [now, then] = latest.currency === previous.currency ? [latest.close, previous.close] : [cad(latest), cad(previous)]
  if (now === null || then === null || then === 0) return null
  const rate = latest.currency === previous.currency && latest.currency === 'USD' ? usdCad : 1
  if (rate === null) return null
  return { cad: position.qty * (now - then) * rate, pct: ((now - then) / then) * 100, day: latest.day }
}
