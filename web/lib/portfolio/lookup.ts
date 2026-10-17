import type { Close } from './types'

/**
 * The last entry on or before `day` in a list sorted by day, or null.
 * Prices and the Bank of Canada rate carry forward over weekends and holidays.
 */
export function onOrBefore<T extends { day: string }>(sorted: readonly T[], day: string): T | null {
  let lo = 0
  let hi = sorted.length - 1
  let found: T | null = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (sorted[mid].day <= day) {
      found = sorted[mid]
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

export interface FxRate {
  day: string
  usdCad: number
}

/** USD/CAD by day (`fx_rates`), sorted. */
export class FxRates {
  readonly rates: readonly FxRate[]

  constructor(rates: readonly FxRate[]) {
    this.rates = [...rates].sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0))
  }

  /** The rate in effect on `day`: that day's, else the last one before it. */
  on(day: string): number | null {
    return onOrBefore(this.rates, day)?.usdCad ?? null
  }

  latest(): FxRate | null {
    return this.rates.at(-1) ?? null
  }

  /** A close in CAD, or null when it's in USD and no rate is known yet. */
  toCad(close: Close, day: string = close.day): number | null {
    if (close.currency === 'CAD') return close.close
    const rate = this.on(day)
    return rate === null ? null : close.close * rate
  }
}

/** Each asset's closes, sorted by day, keyed by `assetKey`. */
export class PriceBook {
  private readonly byKey: Map<string, Close[]>

  constructor(closes: ReadonlyMap<string, readonly Close[]>) {
    this.byKey = new Map(
      [...closes].map(([key, list]) => [key, [...list].sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0))]),
    )
  }

  on(key: string, day: string): Close | null {
    return onOrBefore(this.byKey.get(key) ?? [], day)
  }

  latest(key: string): Close | null {
    return this.byKey.get(key)?.at(-1) ?? null
  }

  days(key: string): string[] {
    return (this.byKey.get(key) ?? []).map((c) => c.day)
  }
}
